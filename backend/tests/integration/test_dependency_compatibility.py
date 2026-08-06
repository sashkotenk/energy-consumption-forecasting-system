from io import BytesIO

import alembic
import asyncpg
import fastapi
import joblib
import numpy as np
import pandas as pd
import pydantic
import sqlalchemy
from sklearn.linear_model import Ridge


def test_production_dependencies_import() -> None:
    modules = (alembic, asyncpg, fastapi, joblib, np, pd, pydantic, sqlalchemy)

    assert all(module is not None for module in modules)


def test_scikit_learn_fit_predict_serialize_load() -> None:
    features = np.array([[0.0], [1.0], [2.0], [3.0]])
    targets = np.array([0.0, 1.0, 2.0, 3.0])
    model = Ridge(alpha=0.1).fit(features, targets)
    expected = model.predict(np.array([[4.0]]))
    buffer = BytesIO()

    joblib.dump(model, buffer)
    buffer.seek(0)
    restored = joblib.load(buffer)

    np.testing.assert_allclose(restored.predict(np.array([[4.0]])), expected)
