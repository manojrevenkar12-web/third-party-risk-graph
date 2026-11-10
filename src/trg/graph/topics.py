"""A purpose-built topic classifier for adverse-media facts: TF-IDF features and a logistic regression, trained on
labelled articles. It runs in about a millisecond on a CPU and costs nothing per call; the model is asked only when
it is unsure (the cascade)."""

from __future__ import annotations

import time

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, make_pipeline


class TopicModel:
    def __init__(self):
        feats = FeatureUnion(
            [
                ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
                ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
            ]
        )
        self.pipe = make_pipeline(feats, LogisticRegression(max_iter=2000, C=8.0))
        self.seconds = 0.0
        self.calls = 0

    def fit(self, texts: list[str], labels: list[str]) -> TopicModel:
        self.pipe.fit(texts, labels)
        return self

    def predict(self, text: str) -> tuple[str, float]:
        t = time.perf_counter()
        p = self.pipe.predict_proba([text])[0]
        self.seconds += time.perf_counter() - t
        self.calls += 1
        i = int(p.argmax())
        return str(self.pipe.classes_[i]), float(p[i])
