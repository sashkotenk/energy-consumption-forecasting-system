"""Machine-learning domain services and reproducibility contracts."""

from energy_forecast.ml.baselines import SeasonalNaive
from energy_forecast.ml.bundles import (
    BUNDLE_FORMAT_VERSION,
    BundleCompatibilityPolicy,
    BundleManifestInput,
    ModelBundleManifest,
    ModelBundleService,
)
from energy_forecast.ml.features import (
    FEATURE_SCHEMA_BASE_V1,
    FEATURE_SCHEMA_QUALITY_V1,
    FeatureMatrix,
    FeaturePipeline,
    FeaturePipelineConfig,
    FeatureRows,
    FeatureSchema,
)
from energy_forecast.ml.metrics import MetricSet, evaluate
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType
from energy_forecast.ml.splits import (
    SPLIT_DEFINITION_V1,
    ChronologicalSplitProtocol,
    FoldData,
    TemporalFold,
    prepare_fold,
)

__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "FEATURE_SCHEMA_BASE_V1",
    "FEATURE_SCHEMA_QUALITY_V1",
    "SPLIT_DEFINITION_V1",
    "AlgorithmRegistry",
    "AlgorithmType",
    "BundleCompatibilityPolicy",
    "BundleManifestInput",
    "ChronologicalSplitProtocol",
    "FeatureMatrix",
    "FeaturePipeline",
    "FeaturePipelineConfig",
    "FeatureRows",
    "FeatureSchema",
    "FoldData",
    "MetricSet",
    "ModelBundleManifest",
    "ModelBundleService",
    "SeasonalNaive",
    "TemporalFold",
    "evaluate",
    "prepare_fold",
]
