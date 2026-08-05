"""
R mirt package wrapper for IRT model fitting.

This module provides a Python interface to the R 'mirt' package,
which is the gold standard for IRT estimation. Communication
happens via subprocess and temporary files.

Note: This is a short-term solution. Long-term, we plan to
implement native Python IRT estimation using PyTorch.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.model_selection import (
    FitStatistics,
    FittedModel,
    IRTModel,
    ItemParameters,
)
from .models import (
    FittingOptions,
    FittingResult,
    FittingStatus,
    IRTModelFitter,
)

logger = logging.getLogger(__name__)


# R script template for mirt fitting
MIRT_SCRIPT_TEMPLATE = '''
# IRTBoss mirt fitting script
# Auto-generated - do not edit

suppressPackageStartupMessages({{
    library(mirt)
    library(jsonlite)
}})

# Read data
data <- read.csv("{data_path}", header=TRUE)

# Model specification
model_type <- "{model_type}"

# Fitting options
max_iter <- {max_iter}
tol <- {tol}

# Define model based on type
if (model_type == "1PL") {{
    # Rasch model - constrain all discriminations to be equal
    model_spec <- mirt.model('F = 1-{n_items}
                              CONSTRAIN = (1-{n_items}, a1)')
    itemtype <- "Rasch"
}} else if (model_type == "2PL") {{
    model_spec <- 1  # Default unidimensional
    itemtype <- "2PL"
}} else if (model_type == "3PL") {{
    model_spec <- 1
    itemtype <- "3PL"
}} else {{
    stop(paste("Unknown model type:", model_type))
}}

# Fit model
tryCatch({{
    if (model_type == "1PL") {{
        fit <- mirt(data, model_spec, itemtype=itemtype,
                   TOL={tol}, technical=list(NCYCLES={max_iter}),
                   verbose=FALSE)
    }} else {{
        fit <- mirt(data, model_spec, itemtype=itemtype,
                   TOL={tol}, technical=list(NCYCLES={max_iter}),
                   verbose=FALSE)
    }}

    # Extract parameters
    params <- coef(fit, IRTpars=TRUE, simplify=TRUE)$items

    # Get fit statistics
    log_lik <- logLik(fit)
    aic <- AIC(fit)
    bic <- BIC(fit)

    # Check convergence
    converged <- fit@OptimInfo$converged

    # Build item parameters list
    item_params <- list()
    for (i in 1:nrow(params)) {{
        item_name <- rownames(params)[i]

        if (model_type == "1PL") {{
            a <- 1.0  # Fixed for Rasch
            b <- params[i, "b"]
            c <- 0.0
        }} else if (model_type == "2PL") {{
            a <- params[i, "a"]
            b <- params[i, "b"]
            c <- 0.0
        }} else {{
            a <- params[i, "a"]
            b <- params[i, "b"]
            c <- params[i, "g"]  # mirt uses 'g' for guessing
        }}

        item_params[[item_name]] <- list(
            item_id = item_name,
            discrimination = a,
            difficulty = b,
            guessing = c
        )
    }}

    # Get number of EM cycles
    n_iter <- fit@OptimInfo$iter

    # Build result
    result <- list(
        success = TRUE,
        converged = converged,
        log_likelihood = as.numeric(log_lik),
        aic = as.numeric(aic),
        bic = as.numeric(bic),
        n_parameters = length(coef(fit)),
        n_iterations = n_iter,
        item_parameters = item_params,
        warnings = character(0)
    )

    # Add any warnings
    if (!converged) {{
        result$warnings <- c(result$warnings,
            "Model did not fully converge. Results may be unstable.")
    }}

}}, error = function(e) {{
    result <<- list(
        success = FALSE,
        converged = FALSE,
        error_message = conditionMessage(e)
    )
}})

# Write result to JSON
write(toJSON(result, auto_unbox=TRUE, pretty=TRUE), "{output_path}")
'''


class MirtWrapper(IRTModelFitter):
    """
    Wrapper for R mirt package.

    Uses subprocess to call R for IRT model fitting.
    Requires R with the 'mirt' and 'jsonlite' packages installed.

    Example:
        wrapper = MirtWrapper()
        if wrapper.is_available():
            result = wrapper.fit(data, IRTModel.TWO_PL)
    """

    def __init__(
        self,
        r_path: str | None = None,
        timeout_seconds: int = 300,
    ):
        """
        Initialize the mirt wrapper.

        Args:
            r_path: Path to R executable. If None, uses 'Rscript' from PATH.
            timeout_seconds: Maximum time for fitting before timeout.
        """
        self.r_path = r_path or "Rscript"
        self.timeout = timeout_seconds
        self._version: str | None = None

    def is_available(self) -> bool:
        """Check if R and mirt are available."""
        try:
            # Try to run a simple R command
            result = subprocess.run(
                [self.r_path, "-e", "library(mirt); cat(packageVersion('mirt'))"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                self._version = result.stdout.strip()
                return True
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_version(self) -> str:
        """Get mirt package version."""
        if self._version is None:
            self.is_available()
        return self._version or "unknown"

    def fit(
        self,
        data: pd.DataFrame,
        model_type: IRTModel,
        options: FittingOptions | None = None,
    ) -> FittingResult:
        """
        Fit an IRT model using R mirt.

        Args:
            data: Response data (rows=respondents, columns=items)
            model_type: Which IRT model to fit
            options: Optional fitting options

        Returns:
            FittingResult with model and status
        """
        import time
        start_time = time.time()

        options = options or FittingOptions()

        # Create temporary files
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.csv"
            script_path = Path(tmpdir) / "fit.R"
            output_path = Path(tmpdir) / "result.json"

            # Write data
            data.to_csv(data_path, index=False)

            # Generate R script
            script = MIRT_SCRIPT_TEMPLATE.format(
                data_path=str(data_path).replace("\\", "/"),
                model_type=model_type.value,
                n_items=len(data.columns),
                max_iter=options.max_iterations,
                tol=options.convergence_threshold,
                output_path=str(output_path).replace("\\", "/"),
            )

            script_path.write_text(script)

            # Run R
            try:
                result = subprocess.run(
                    [self.r_path, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )

                if result.returncode != 0:
                    logger.error(f"R script failed: {result.stderr}")
                    return FittingResult(
                        model_type=model_type,
                        status=FittingStatus.ERROR,
                        error_message=f"R execution failed: {result.stderr[:500]}",
                        fitting_time_seconds=time.time() - start_time,
                    )

                # Parse result
                if not output_path.exists():
                    return FittingResult(
                        model_type=model_type,
                        status=FittingStatus.ERROR,
                        error_message="R script did not produce output",
                        fitting_time_seconds=time.time() - start_time,
                    )

                with open(output_path) as f:
                    r_result = json.load(f)

            except subprocess.TimeoutExpired:
                return FittingResult(
                    model_type=model_type,
                    status=FittingStatus.ERROR,
                    error_message=f"Fitting timed out after {self.timeout} seconds",
                    fitting_time_seconds=self.timeout,
                )
            except Exception as e:
                logger.exception("Error running mirt")
                return FittingResult(
                    model_type=model_type,
                    status=FittingStatus.ERROR,
                    error_message=str(e),
                    fitting_time_seconds=time.time() - start_time,
                )

        # Convert R result to Python objects
        return self._parse_result(r_result, model_type, time.time() - start_time)

    def _parse_result(
        self,
        r_result: dict,
        model_type: IRTModel,
        fitting_time: float,
    ) -> FittingResult:
        """Parse the JSON result from R into Python objects."""
        if not r_result.get("success", False):
            return FittingResult(
                model_type=model_type,
                status=FittingStatus.ERROR,
                error_message=r_result.get("error_message", "Unknown error"),
                fitting_time_seconds=fitting_time,
            )

        # Build item parameters
        item_params = []
        for item_id, params in r_result["item_parameters"].items():
            item_params.append(ItemParameters(
                item_id=params["item_id"],
                discrimination=params["discrimination"],
                difficulty=params["difficulty"],
                guessing=params.get("guessing", 0.0),
            ))

        # Build fit statistics
        fit_stats = FitStatistics(
            log_likelihood=r_result["log_likelihood"],
            aic=r_result["aic"],
            bic=r_result["bic"],
            n_parameters=r_result["n_parameters"],
            converged=r_result["converged"],
            n_iterations=r_result.get("n_iterations", 0),
        )

        # Build fitted model
        fitted_model = FittedModel(
            model_type=model_type,
            fit_stats=fit_stats,
            item_parameters=item_params,
            warnings=r_result.get("warnings", []),
        )

        # Determine status
        if r_result["converged"]:
            status = FittingStatus.SUCCESS
        else:
            status = FittingStatus.CONVERGED_WITH_WARNINGS

        return FittingResult(
            model_type=model_type,
            status=status,
            model=fitted_model,
            warnings=r_result.get("warnings", []),
            fitting_time_seconds=fitting_time,
            n_iterations=r_result.get("n_iterations", 0),
        )

    def fit_all(
        self,
        data: pd.DataFrame,
        options: FittingOptions | None = None,
        include_3pl: bool = False,
    ) -> dict[IRTModel, FittingResult]:
        """
        Fit all appropriate IRT models.

        Fits models in order of complexity: 1PL → 2PL → 3PL.
        The 3PL is only fitted if include_3pl is True.
        """
        results = {}

        # Always fit 1PL
        results[IRTModel.RASCH] = self.fit(data, IRTModel.RASCH, options)

        # Always fit 2PL
        results[IRTModel.TWO_PL] = self.fit(data, IRTModel.TWO_PL, options)

        # Optionally fit 3PL
        if include_3pl:
            results[IRTModel.THREE_PL] = self.fit(data, IRTModel.THREE_PL, options)

        return results

    def estimate_abilities(
        self,
        fitted_model: FittedModel,
        data: pd.DataFrame,
        method: str = "EAP",
    ) -> np.ndarray:
        """
        Estimate ability scores using the fitted model.

        This requires re-running R with the fitted parameters,
        which is not ideal but necessary with the subprocess approach.
        """
        # For now, use a simple MAP estimate computed in Python
        # This is a placeholder until we have proper R integration
        n_respondents = len(data)
        abilities = np.zeros(n_respondents)

        for i in range(n_respondents):
            responses = data.iloc[i].values
            abilities[i] = self._estimate_single_ability(
                responses, fitted_model, method
            )

        return abilities

    def _estimate_single_ability(
        self,
        responses: np.ndarray,
        model: FittedModel,
        method: str,
    ) -> float:
        """
        Estimate ability for a single respondent.

        Uses grid search with EAP estimation.
        """
        theta_grid = np.linspace(-4, 4, 81)
        log_likelihoods = np.zeros_like(theta_grid)

        for item in model.item_parameters:
            idx = list(range(len(model.item_parameters))).index(
                model.item_parameters.index(item)
            )

            if idx >= len(responses) or np.isnan(responses[idx]):
                continue

            response = int(responses[idx])
            a = item.discrimination
            b = item.difficulty
            c = item.guessing

            # Probability of correct response
            z = a * (theta_grid - b)
            p = c + (1 - c) / (1 + np.exp(-z))

            # Add to log-likelihood
            if response == 1:
                log_likelihoods += np.log(np.maximum(p, 1e-10))
            else:
                log_likelihoods += np.log(np.maximum(1 - p, 1e-10))

        if method == "EAP":
            # Expected a posteriori with standard normal prior
            prior = np.exp(-0.5 * theta_grid ** 2)
            posterior = np.exp(log_likelihoods) * prior
            posterior /= posterior.sum()
            return float(np.sum(theta_grid * posterior))
        else:
            # MAP / ML
            return float(theta_grid[np.argmax(log_likelihoods)])


class DummyFitter(IRTModelFitter):
    """
    Dummy fitter for testing when R is not available.

    Generates synthetic parameter estimates that are reasonable
    but not actually fitted to the data.
    """

    def fit(
        self,
        data: pd.DataFrame,
        model_type: IRTModel,
        options: FittingOptions | None = None,
    ) -> FittingResult:
        """Generate dummy fitted model."""
        logger.warning("Using DummyFitter - results are not real!")

        n_items = len(data.columns)
        item_params = []

        np.random.seed(42)

        for i, col in enumerate(data.columns):
            # Generate reasonable-looking parameters
            item_mean = data[col].mean()
            difficulty = -2 + 4 * (1 - item_mean)  # Rough conversion

            if model_type == IRTModel.RASCH:
                discrimination = 1.0
            else:
                discrimination = 0.5 + np.random.rand() * 1.5

            guessing = 0.0
            if model_type == IRTModel.THREE_PL:
                guessing = 0.1 + np.random.rand() * 0.15

            item_params.append(ItemParameters(
                item_id=col,
                discrimination=discrimination,
                difficulty=difficulty,
                guessing=guessing,
            ))

        # Generate dummy fit statistics
        n_params = n_items * (1 if model_type == IRTModel.RASCH else 2)
        if model_type == IRTModel.THREE_PL:
            n_params = n_items * 3

        fit_stats = FitStatistics(
            log_likelihood=-1000 - np.random.rand() * 100,
            aic=2000 + n_params * 2,
            bic=2000 + n_params * np.log(len(data)),
            n_parameters=n_params,
            converged=True,
            n_iterations=50,
        )

        fitted_model = FittedModel(
            model_type=model_type,
            fit_stats=fit_stats,
            item_parameters=item_params,
            warnings=["Using dummy fitter - parameters are synthetic"],
        )

        return FittingResult(
            model_type=model_type,
            status=FittingStatus.SUCCESS,
            model=fitted_model,
            warnings=["Using dummy fitter - parameters are synthetic"],
            fitting_time_seconds=0.1,
            n_iterations=50,
        )

    def fit_all(
        self,
        data: pd.DataFrame,
        options: FittingOptions | None = None,
        include_3pl: bool = False,
    ) -> dict[IRTModel, FittingResult]:
        """Fit all models using dummy fitter."""
        results = {
            IRTModel.RASCH: self.fit(data, IRTModel.RASCH, options),
            IRTModel.TWO_PL: self.fit(data, IRTModel.TWO_PL, options),
        }
        if include_3pl:
            results[IRTModel.THREE_PL] = self.fit(data, IRTModel.THREE_PL, options)
        return results

    def estimate_abilities(
        self,
        fitted_model: FittedModel,
        data: pd.DataFrame,
        method: str = "EAP",
    ) -> np.ndarray:
        """Generate dummy ability estimates."""
        # Simple sum score conversion
        sum_scores = data.sum(axis=1) / len(data.columns)
        # Convert to theta scale
        return (sum_scores - 0.5) * 4


def get_fitter() -> IRTModelFitter:
    """
    Get the best available IRT fitter.

    Returns MirtWrapper if R/mirt is available, otherwise DummyFitter.
    """
    mirt = MirtWrapper()
    if mirt.is_available():
        logger.info(f"Using mirt version {mirt.get_version()}")
        return mirt
    else:
        logger.warning(
            "R/mirt not available. Using dummy fitter. "
            "Install R and the mirt package for real IRT estimation."
        )
        return DummyFitter()
