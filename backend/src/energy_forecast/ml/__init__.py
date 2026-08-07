"""Machine-learning domain services and reproducibility contracts."""

from energy_forecast.ml.features import (
    FEATURE_SCHEMA_BASE_V1,
    FEATURE_SCHEMA_QUALITY_V1,
    FeatureMatrix,
    FeaturePipeline,
    FeaturePipelineConfig,
    FeatureRows,
    FeatureSchema,
)
from energy_forecast.ml.splits import (
    SPLIT_DEFINITION_V1,
    ChronologicalSplitProtocol,
    FoldData,
    TemporalFold,
    prepare_fold,
)

__all__ = [
    "FEATURE_SCHEMA_BASE_V1",
    "FEATURE_SCHEMA_QUALITY_V1",
    "SPLIT_DEFINITION_V1",
    "ChronologicalSplitProtocol",
    "FeatureMatrix",
    "FeaturePipeline",
    "FeaturePipelineConfig",
    "FeatureRows",
    "FeatureSchema",
    "FoldData",
    "TemporalFold",
    "prepare_fold",
]
