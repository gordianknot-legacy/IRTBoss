# Fit every validation fixture with mirt and write the estimates as JSON.
#
# mirt is the reference implementation this project is checked against. It is
# not a runtime dependency: nothing the product does at request time touches R.
# It exists so that a disagreement between two independently written estimators
# fitting the same likelihood to the same data shows up as a failing build.
#
# Usage:
#   Rscript tests/validation/mirt_reference.R
#
# Writes <fixture>.mirt.json beside each <fixture>.csv.

suppressPackageStartupMessages({
  library(mirt)
  library(jsonlite)
})

# Resolve the fixtures directory relative to this script, falling back to the
# repository-root-relative path when the script path is unavailable.
script_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_arg) > 0) {
  dirname(sub("^--file=", "", script_arg[1]))
} else {
  "tests/validation"
}

fixtures_dir <- file.path(script_dir, "fixtures")
if (!dir.exists(fixtures_dir)) {
  fixtures_dir <- "tests/validation/fixtures"
}
if (!dir.exists(fixtures_dir)) {
  stop("cannot locate the fixtures directory; run from the backend/ directory")
}

manifest <- fromJSON(file.path(fixtures_dir, "manifest.json"),
                     simplifyVector = FALSE)

# mirt's internal parameterisation is slope-intercept (a * theta + d). Asking
# for IRTpars converts to the a / b / g form this project reports, which avoids
# hand-converting and getting a sign wrong.
extract_pars <- function(model_obj, model_key) {
  pars <- coef(model_obj, IRTpars = TRUE, simplify = TRUE)$items

  out <- list()
  out$discrimination <- as.numeric(pars[, "a"])

  if (model_key %in% c("rasch", "2pl", "3pl")) {
    out$difficulty <- as.numeric(pars[, "b"])
    if (model_key == "3pl") {
      out$guessing <- as.numeric(pars[, "g"])
    }
  } else {
    # Graded: one b column per category boundary.
    b_cols <- grep("^b[0-9]+$", colnames(pars), value = TRUE)
    out$thresholds <- lapply(seq_len(nrow(pars)), function(i) {
      as.numeric(pars[i, b_cols])
    })
  }
  out
}

mirt_model_for <- function(model_key) {
  switch(model_key,
    "rasch" = "Rasch",
    "2pl"   = "2PL",
    "3pl"   = "3PL",
    "grm"   = "graded",
    stop(paste("unsupported model:", model_key))
  )
}

for (name in names(manifest)) {
  entry <- manifest[[name]]
  model_key <- entry$model
  csv_path <- file.path(fixtures_dir, paste0(name, ".csv"))
  data <- read.csv(csv_path)

  cat(sprintf("fitting %s (%s)...\n", name, model_key))

  itemtype <- mirt_model_for(model_key)

  # The 3PL lower asymptote is weakly identified. This project applies a
  # Beta(5, 17) prior to it; the same prior is applied here so that the two
  # estimators are maximising the same objective. Without it the comparison
  # would measure the prior, not the implementation.
  if (model_key == "3pl") {
    n_items <- entry$n_items
    prior_syntax <- sprintf(
      "F = 1-%d\n PRIOR = (1-%d, g, expbeta, 5, 17)", n_items, n_items
    )
    model_spec <- mirt.model(prior_syntax)
    fit_obj <- mirt(data, model_spec, itemtype = itemtype,
                    technical = list(NCYCLES = 2000), verbose = FALSE)
  } else if (model_key == "rasch") {
    # mirt's "Rasch" fixes every slope at 1 and frees the latent variance,
    # matching this project's Rasch rather than its 1PL.
    fit_obj <- mirt(data, 1, itemtype = itemtype,
                    technical = list(NCYCLES = 2000), verbose = FALSE)
  } else {
    fit_obj <- mirt(data, 1, itemtype = itemtype,
                    technical = list(NCYCLES = 2000), verbose = FALSE)
  }

  pars <- extract_pars(fit_obj, model_key)

  result <- list(
    fixture = name,
    model = model_key,
    mirt_version = as.character(packageVersion("mirt")),
    converged = extract.mirt(fit_obj, "converged"),
    log_likelihood = as.numeric(logLik(fit_obj)),
    n_estimated_parameters = extract.mirt(fit_obj, "nest"),
    latent_variance = as.numeric(coef(fit_obj, simplify = TRUE)$cov[1, 1]),
    items = pars
  )

  out_path <- file.path(fixtures_dir, paste0(name, ".mirt.json"))
  write(toJSON(result, auto_unbox = TRUE, digits = 10, pretty = TRUE),
        out_path)
  cat(sprintf("  wrote %s\n", out_path))
}

cat("done\n")
