"""LLM step: turn a free-text rental post (Italian or English) into structured facts.

The model only extracts what the post says. It never decides whether the room
suits anyone; hh/rules.py does that with plain code, so every reject has a
reason that can be checked against the post.
"""
import json
import re

SYSTEM = """You read rental posts from Facebook and Telegram groups in Padova, Italy.
Posts are in Italian or English. Extract facts exactly as the post states them.
Never guess: when the post does not say something, use null or "unknown".
Reply with ONE JSON object and nothing else."""

INSTR = """Today is {today}. Extract this JSON from the post below.

{{
 "kind": "offer" | "seeking" | "other",
   // offer = someone renting out a room/flat/bed, INCLUDING flatmates looking for a new flatmate
   //   ("cerchiamo un/una coinquilino/a", "si libera una stanza", "looking for a flatmate") = offer
   // seeking = a person LOOKING FOR a room for themselves ("cerco stanza", "looking for a room"); other = anything else
 "units": [ {{"type": "single_room" | "double_room" | "bed_in_shared_room" | "studio" | "apartment" | "unknown",
             "rent_eur": number or null,          // monthly rent for this unit, per person
             "rent_basis": "base" | "all_inclusive" | "unknown",
                // all_inclusive = "tutto incluso", "spese incluse", "bills included"; base = bills/spese/utenze are extra
             "bills_eur": number or null }} ],     // monthly bills/condominio on top of rent, if stated
   // one entry per distinct room offered; "stanza singola"/"camera singola"/"singola" = single_room,
   // "doppia" = double_room, "posto letto" = bed_in_shared_room, "monolocale" = studio
 "available_from": "YYYY-MM-DD" or null,   // "subito"/"immediately"/"da ora" = today; a month alone = its first day
 "available_note": short string or null,   // e.g. "da novembre", "fino a giugno", "subito"
 "gender": "female_only" | "male_only" | "any" | "unknown",
   // female_only: "solo ragazze", "solo donne", "per ragazza", "studentessa/lavoratrice" (feminine only), "girls only"
   // male_only: "solo ragazzi", "solo uomini", "per ragazzo", "boys only"
   // any: explicitly open to both ("ragazzo o ragazza", "anche ragazzi")
 "tenant": "students_only" | "workers_only" | "students_or_workers" | "unknown",
   // students_only: "solo studenti/studentesse", "riservato a studenti", "students only"
   // students_or_workers: "studenti o lavoratori", "anche lavoratori"
 "room_location": short string or null,   // WHERE THE ROOM IS: street, zone or town, copied from the post
 "nearby": [short strings],               // places mentioned only as distance/reference ("10 min da Prato della Valle", "vicino all'ospedale")
 "min_stay_months": number or null,
 "phone": string or null,
 "summary_en": one short English sentence describing the offer
}}

POST:
<<<
{post}
>>>"""

FIELDS = ("kind", "units", "available_from", "available_note", "gender", "tenant",
          "room_location", "nearby", "min_stay_months", "phone", "summary_en")


def build_messages(post, today):
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": INSTR.format(today=today, post=post.strip()[:4000])}]


def parse(text):
    """Pull the JSON object out of the model's reply; None if there isn't a usable one."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            try:
                d = json.loads(text[start:i + 1])
            except json.JSONDecodeError:
                return None
            break
    else:
        return None
    if not isinstance(d, dict) or "kind" not in d:
        return None
    d = {k: d.get(k) for k in FIELDS}
    d["units"] = [u for u in (d["units"] or []) if isinstance(u, dict)]
    d["nearby"] = [n for n in (d["nearby"] or []) if isinstance(n, str)]
    return d


class LocalLLM:
    """A Hugging Face chat model on the cluster GPU (Qwen3.5 or Gemma 4)."""

    def __init__(self, path, max_new_tokens=500):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForImageTextToText
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        from pathlib import Path
        if not torch.cuda.is_available():  # CPU-only job: a 4B model is slow but workable for a few posts an hour
            self.model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16)
            self.model.eval()
            self.max_new_tokens = max_new_tokens
            self.name = path.rstrip("/").split("/")[-1] + "-cpu"
            return
        gpu_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        weights_gb = sum(f.stat().st_size for f in Path(path).glob("*.safetensors")) / 2**30
        half = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        kw = {"device_map": "cuda:0", "dtype": half}
        if weights_gb + 3 > gpu_gb:  # only quantize when 16-bit weights won't fit: 8-bit is ~5x slower
            from transformers import BitsAndBytesConfig
            kw = {"device_map": "cuda:0", "quantization_config": BitsAndBytesConfig(load_in_8bit=True)}
        try:
            self.model = AutoModelForCausalLM.from_pretrained(path, **kw)
        except (ValueError, KeyError):
            self.model = AutoModelForImageTextToText.from_pretrained(path, **kw)
        self.model.eval()
        self.max_new_tokens = max_new_tokens
        self.name = path.rstrip("/").split("/")[-1]

    def __call__(self, messages):
        try:
            prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=False)
        except TypeError:
            prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        ids = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens, do_sample=False)
        return self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
