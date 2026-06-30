"""Backward-compatible re-export — prefer ``configuration.uipath_api``."""

from configuration.uipath_api import UiPathOrchestratorClient, UiPathOrchestratorError

__all__ = ["UiPathOrchestratorClient", "UiPathOrchestratorError"]
