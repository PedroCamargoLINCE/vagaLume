"""A probable field for roles the keyword rules can't place.

About one role in six has no field: mostly titles in French, German, Swedish or Chinese ("STAGE -
Câblage & Intégration Avionique", "Duales Studium Informatik"), languages the word lists in
radar/fields.py don't know. A small multilingual model turns each title into 384 numbers that stand
for its meaning, so titles that mean the same thing get close numbers in any language. A role
without a field gets the fields most common among the 10 roles with the closest titles that do
have one (both fields when the neighbours split between two).

Measured on 2026-10-27: on 2,000 roles whose field we knew, 98% right where it answers; on roles
without a field, read by hand, about 78% right. That is good enough to move a role up the list for
students of that field, not to hide it from anyone else, so the site only sorts by it.

Optional: needs `pip install ".[embeddings]"` (onnxruntime, tokenizers, huggingface_hub). Without
it, nothing is guessed and the run goes on. The model (multilingual-e5-small, the quantized ONNX
file that Transformers.js also uses, about 130 MB) is downloaded once and cached.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from .labels import classify_regions
from .models import Opportunity

log = logging.getLogger(__name__)

MODEL = "Xenova/multilingual-e5-small"
NEIGHBOURS = 10
MIN_SHARE = 0.6  # the top field must hold this share of the neighbours' weight, else no guess
SECOND_SHARE = 0.3  # a second field this strong is kept too ("radar" roles: engenharia + computacao)

# Words that say "internship" and nothing about the field, in the languages of the titles.
_FILLER = re.compile(
    r"\b(?:summer|winter|spring|fall|autumn|intern(?:ship)?s?|stage|stagiaire|est[áa]gi\w*|praktik\w*|trainee|apprenti\w*|"
    r"alternan\w*|student\w*|programa?|program(?:me)?|oportunidades?|vagas?|diferentes|[áa]reas?|varias|banco|talentos|"
    r"university|recruiting|early|careers?|day|jovem|aprendiz|20\d\d|h/f|f/h|m/w/d|em|de|in|the|for|na|no)\b", re.I)


def says_nothing(title: str) -> bool:
    """ "Internship", "Summer 2027 Interns - South Carolina", "ESTÁGIO – OPORTUNIDADES EM DIFERENTES ÁREAS":
    nothing but "internship" and maybe a place. Guessing a field from these would be a coin toss."""
    rest = " ".join(re.findall(r"[^\W\d_]{2,}", _FILLER.sub(" ", title)))
    return len(rest) < 3 or classify_regions(rest) != ["unknown"]


def needs_guess(opp: Opportunity) -> bool:
    return not opp.fields and opp.area == "other" and opp.source != "programs" and not says_nothing(opp.title)


def vote(similarities: Any, neighbour_fields: list[list[str]]) -> list[str]:
    """Fields from the neighbours' similarities (one row of scores, best first or not) and their fields."""
    import numpy as np

    best = np.argsort(-similarities)[:NEIGHBOURS]
    weights: Counter[str] = Counter()
    for index in best:
        for name in neighbour_fields[index]:
            weights[name] += float(similarities[index])
    total = float(sum(similarities[index] for index in best))
    if not weights or total <= 0:
        return []
    ranked = [(name, weight / total) for name, weight in weights.most_common(2)]
    if ranked[0][1] < MIN_SHARE:
        return []
    return [ranked[0][0]] + [name for name, share in ranked[1:] if share >= SECOND_SHARE]


class _Embedder:
    def __init__(self) -> None:
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.session = onnxruntime.InferenceSession(hf_hub_download(MODEL, "onnx/model_quantized.onnx"))
        self.tokenizer = Tokenizer.from_file(hf_hub_download(MODEL, "tokenizer.json"))
        self.tokenizer.enable_truncation(64)  # titles
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        self.inputs = {i.name for i in self.session.get_inputs()}

    def __call__(self, titles: list[str]) -> Any:
        import numpy as np

        chunks = []
        for start in range(0, len(titles), 64):
            encoded = self.tokenizer.encode_batch(["query: " + t for t in titles[start:start + 64]])
            ids = np.array([e.ids for e in encoded])
            mask = np.array([e.attention_mask for e in encoded])
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feeds)[0]
            vectors = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)  # mean of the words
            chunks.append(vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
        return np.vstack(chunks).astype(np.float32)


def fill(opportunities: list[Opportunity]) -> int:
    """Set `guess` on the roles that need one. Returns how many got a guess (0 without the model)."""
    targets = [o for o in opportunities if needs_guess(o)]
    known = [o for o in opportunities if o.fields]
    if not targets or len(known) < NEIGHBOURS:
        return 0
    try:
        embed = _Embedder()
    except Exception as error:  # noqa: BLE001 - not installed, or the model couldn't be downloaded
        log.info("No field guesses today (%s: %s)", type(error).__name__, error)
        return 0
    known_vectors = embed([o.title for o in known])
    target_vectors = embed([o.title for o in targets])
    known_fields = [o.fields for o in known]
    guessed = 0
    for start in range(0, len(targets), 512):  # 512 x 20,000 scores at a time
        scores = target_vectors[start:start + 512] @ known_vectors.T
        for opp, row in zip(targets[start:start + 512], scores):
            opp.guess = vote(row, known_fields)
            guessed += bool(opp.guess)
    log.info("Field guesses: %d of %d roles without a field", guessed, len(targets))
    return guessed
