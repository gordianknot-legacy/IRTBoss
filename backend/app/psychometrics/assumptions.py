"""
The two assumptions every unidimensional IRT model rests on.

Fitting a 2PL to data and reporting its parameters presumes two things that the
data itself has to be asked about:

* **Unidimensionality** - one latent trait accounts for the covariation among
  items. If two traits are present, the single theta scale is a blend of them,
  and every item parameter, every information curve and every reported
  reliability describes a construct nobody defined.
* **Local independence** - conditional on theta, responses are independent. When
  a pair of items shares something the trait does not explain (a common stimulus,
  a cue in one item that gives away another), that pair effectively counts as
  less than two items. Test information is then overstated and reliability
  inflated, in the direction that flatters the test.

Both are examined here from the *polychoric* correlation matrix rather than the
Pearson matrix. Pearson correlations between binary or coarsely ordered items are
attenuated by the coarseness itself and produce spurious "difficulty factors" -
factors that group items by their p-values rather than by their content. The
polychoric correlation estimates the correlation of the continuous variables
assumed to underlie the observed categories, and does not have this artefact.

Nothing in this module returns a bare verdict. Dimensionality decisions rest on
judgement that a rule cannot encode, and each statistic here carries the
conditions under which it is informative.

Deliberate scope limits, stated once here and repeated in the ``notes`` of the
objects concerned:

* The bifactor decomposition is a **Schmid-Leiman-style approximation** built
  from principal components, not a fitted bifactor model. See
  :func:`bifactor_approximation`.
* The Q3 bootstrap null holds the fitted item parameters fixed rather than
  refitting each replication. See :func:`local_independence`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize
from scipy.special import ndtr, ndtri

from app.irt.em import MISSING, ResponseMatrix
from app.irt.families import ItemParameters, get_family

from .information import category_probabilities

_FLOOR = 1e-12

# Thresholds and the sentinels that stand in for +/- infinity when the bivariate
# normal rectangle is evaluated. Phi(8) differs from 1 by about 6e-16, so the
# sentinels are exact to double precision while keeping every exponent finite -
# passing a literal inf produces inf - inf inside the density and yields NaN.
_TAU_LIMIT = 6.0
_TAU_SENTINEL = 8.0

# Gauss-Legendre nodes for the Drezner-Wesolowsky integral below. 32 points hold
# the bivariate normal CDF to roughly 1e-10 for |rho| <= 0.999, far tighter than
# the 1e-4 tolerance the correlation is optimised to.
_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(32)

# The likelihood is singular at |rho| = 1, so the search stops just short of it.
_RHO_LIMIT = 0.999


# --------------------------------------------------------------------------- #
# Bivariate normal machinery
# --------------------------------------------------------------------------- #


def _bvn_cdf(h: np.ndarray, k: np.ndarray, rho: float) -> np.ndarray:
    """P(Z1 <= h, Z2 <= k) for a standard bivariate normal with correlation rho.

    Uses the Drezner-Wesolowsky identity, which writes the CDF as the
    independent-case product plus the integral of the bivariate density over the
    correlation itself::

        Phi2(h, k, rho) = Phi(h) Phi(k) + int_0^rho phi2(h, k, r) dr

    The integrand is smooth and bounded on the path of integration for
    |rho| < 1, so fixed-order Gauss-Legendre converges quickly. Doing it this way
    rather than calling ``scipy.stats.multivariate_normal.cdf`` matters because
    the polychoric optimiser evaluates a whole threshold grid at once, thousands
    of times per matrix; this form is fully vectorised over the grid.
    """
    rho = float(np.clip(rho, -_RHO_LIMIT, _RHO_LIMIT))
    independent = ndtr(h) * ndtr(k)
    if rho == 0.0:
        return independent

    r = 0.5 * rho * (_GL_NODES + 1.0)                     # nodes on [0, rho]
    w = 0.5 * rho * _GL_WEIGHTS
    r = r[:, None, None]

    one_minus = 1.0 - r**2
    exponent = -(h[None] ** 2 - 2.0 * r * h[None] * k[None] + k[None] ** 2) / (
        2.0 * one_minus
    )
    density = np.exp(exponent) / (2.0 * np.pi * np.sqrt(one_minus))
    return independent + np.tensordot(w, density, axes=(0, 0))


def _cell_probabilities(
    tau_x: np.ndarray, tau_y: np.ndarray, rho: float
) -> np.ndarray:
    """Model probability of each cell of the ``Kx x Ky`` contingency table."""
    h = np.concatenate([[-_TAU_SENTINEL], tau_x, [_TAU_SENTINEL]])[:, None]
    k = np.concatenate([[-_TAU_SENTINEL], tau_y, [_TAU_SENTINEL]])[None, :]
    cumulative = _bvn_cdf(np.broadcast_to(h, (h.size, k.size)),
                          np.broadcast_to(k, (h.size, k.size)), rho)
    cells = (
        cumulative[1:, 1:] - cumulative[:-1, 1:]
        - cumulative[1:, :-1] + cumulative[:-1, :-1]
    )
    return np.clip(cells, _FLOOR, 1.0)


def _thresholds(column: np.ndarray, n_cat: int) -> np.ndarray:
    """Normal-scale cut points from an item's univariate marginal proportions.

    This is the first half of the two-step estimator: thresholds come from the
    marginals alone and are then held fixed while each pair's correlation is
    optimised. Full-information joint ML would estimate them simultaneously and
    is marginally more efficient, but the two-step estimator is consistent, is
    what every standard implementation reports, and cannot be dragged around by
    a single badly behaved pair.
    """
    observed = column[column != MISSING]
    if observed.size == 0:
        return np.zeros(n_cat - 1, dtype=float)
    counts = np.bincount(observed.astype(int), minlength=n_cat).astype(float)
    cumulative = np.cumsum(counts)[: n_cat - 1] / observed.size
    # An empty extreme category would map to +/- infinity; clipping puts it at
    # the edge of the usable range instead of poisoning the pair.
    tau = ndtri(np.clip(cumulative, 1e-6, 1.0 - 1e-6))
    return np.clip(tau, -_TAU_LIMIT, _TAU_LIMIT)


def polychoric_correlation(
    x: np.ndarray,
    y: np.ndarray,
    n_cat_x: int,
    n_cat_y: int,
    *,
    tau_x: np.ndarray | None = None,
    tau_y: np.ndarray | None = None,
) -> float:
    """Two-step ML polychoric correlation for one pair of ordinal items.

    Only rows where both items were answered contribute. Returns 0.0 when the
    pair carries no information - fewer than two joint observations, or either
    item constant among them - rather than an arbitrary value, and the caller is
    told how many such pairs there were.
    """
    both = (x != MISSING) & (y != MISSING)
    xi = x[both].astype(int)
    yi = y[both].astype(int)
    if xi.size < 2 or np.unique(xi).size < 2 or np.unique(yi).size < 2:
        return 0.0

    if tau_x is None:
        tau_x = _thresholds(xi, n_cat_x)
    if tau_y is None:
        tau_y = _thresholds(yi, n_cat_y)

    counts = np.bincount(
        xi * n_cat_y + yi, minlength=n_cat_x * n_cat_y
    ).reshape(n_cat_x, n_cat_y).astype(float)

    def negative_loglik(rho: float) -> float:
        return -float(
            np.sum(counts * np.log(_cell_probabilities(tau_x, tau_y, rho)))
        )

    result = optimize.minimize_scalar(
        negative_loglik,
        bounds=(-_RHO_LIMIT, _RHO_LIMIT),
        method="bounded",
        options={"xatol": 1e-5},
    )
    return float(np.clip(result.x, -1.0, 1.0))


@dataclass(frozen=True)
class PolychoricMatrix:
    """Polychoric correlations with the conditions under which they hold."""

    matrix: np.ndarray                 # (n_items, n_items), unit diagonal
    item_ids: list[str]
    thresholds: list[np.ndarray]
    min_pair_n: int
    notes: list[str] = field(default_factory=list)

    JSON_PROPERTIES = ('is_positive_definite',)

    @property
    def is_positive_definite(self) -> bool:
        return bool(np.linalg.eigvalsh(self.matrix).min() > 1e-10)


def polychoric_matrix(data: ResponseMatrix) -> PolychoricMatrix:
    """Full polychoric correlation matrix, pairwise complete.

    Thresholds are estimated once per item from all of that item's observed
    responses; only the correlation is re-estimated per pair. Estimating
    thresholds within each pair instead would make the matrix depend on which
    pairs happened to be complete, which is a worse failure than the slight
    inconsistency this choice leaves behind under non-ignorable missingness.
    """
    values = data.values
    n_items = data.n_items
    n_cat = data.n_categories.astype(int)
    notes: list[str] = []

    taus = [_thresholds(values[:, j], int(n_cat[j])) for j in range(n_items)]

    matrix = np.eye(n_items, dtype=float)
    min_pair_n = data.n_persons
    degenerate = 0

    for j in range(n_items):
        for m in range(j + 1, n_items):
            both = (values[:, j] != MISSING) & (values[:, m] != MISSING)
            pair_n = int(both.sum())
            min_pair_n = min(min_pair_n, pair_n)
            rho = polychoric_correlation(
                values[:, j], values[:, m], int(n_cat[j]), int(n_cat[m]),
                tau_x=taus[j], tau_y=taus[m],
            )
            if rho == 0.0:
                degenerate += 1
            matrix[j, m] = matrix[m, j] = rho

    if degenerate:
        notes.append(
            f"{degenerate} item pair(s) carried no usable joint information "
            "(a constant item or too few complete pairs) and were set to zero "
            "correlation; treat any factor solution as provisional."
        )
    if min_pair_n < 200:
        notes.append(
            f"The sparsest item pair had only {min_pair_n} joint observations. "
            "Polychoric estimates are noticeably unstable below roughly 200."
        )

    smallest = float(np.linalg.eigvalsh(matrix).min())
    if smallest < -1e-8:
        notes.append(
            f"The matrix is not positive definite (smallest eigenvalue "
            f"{smallest:.3f}). This is ordinary for a pairwise-estimated "
            "polychoric matrix; the eigenvalue-based procedures below are "
            "applied to the nearest positive-definite matrix instead."
        )

    return PolychoricMatrix(
        matrix=matrix,
        item_ids=list(data.item_ids),
        thresholds=taus,
        min_pair_n=min_pair_n,
        notes=notes,
    )


def _nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    """Nearest positive-definite correlation matrix by eigenvalue clipping.

    Pairwise estimation gives no guarantee of positive definiteness, and a
    negative eigenvalue makes partial correlations and factor extraction
    meaningless. Clipping the spectrum and rescaling to a unit diagonal is the
    cheapest repair that preserves the matrix's leading structure.
    """
    values, vectors = np.linalg.eigh(matrix)
    if values.min() > 1e-10:
        return matrix
    repaired = (vectors * np.clip(values, 1e-8, None)) @ vectors.T
    scale = np.sqrt(np.diag(repaired))
    return repaired / np.outer(scale, scale)


# --------------------------------------------------------------------------- #
# Parallel analysis
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EigenvalueRow:
    """One component's observed eigenvalue against its random-data reference."""

    component: int                 # 1-based
    observed: float
    random_mean: float
    random_p95: float
    retained: bool


@dataclass(frozen=True)
class ParallelAnalysisResult:
    n_factors_retained: int
    eigenvalues: list[EigenvalueRow]
    n_iterations: int
    percentile: float
    seed: int
    notes: list[str] = field(default_factory=list)


def parallel_analysis(
    data: ResponseMatrix,
    observed_matrix: np.ndarray,
    *,
    n_iterations: int = 100,
    percentile: float = 95.0,
    seed: int = 20260803,
) -> ParallelAnalysisResult:
    """Horn's parallel analysis on the polychoric matrix.

    An eigenvalue above 1 means little on its own: sampling noise alone produces
    leading eigenvalues well above 1 whenever items outnumber respondents by any
    appreciable fraction. Parallel analysis replaces that fixed reference with an
    empirical one - the eigenvalues that data of this exact shape produce when
    there is no common factor at all.

    The random datasets resample each item's observed responses independently,
    so every simulated item has the *same* marginal distribution as its real
    counterpart while all covariation is destroyed. Matching the marginals is
    what makes the reference honest for ordinal data: the number of categories
    and the skew of each item both affect the eigenvalues of a polychoric matrix.

    Retention stops at the first component that fails, so the count is the length
    of the initial run of components exceeding their reference, not the total
    number that happen to exceed it.
    """
    rng = np.random.default_rng(seed)
    n_items = data.n_items
    n_persons = data.n_persons
    n_cat = data.n_categories.astype(int)
    notes: list[str] = []

    observed_eigen = np.sort(
        np.linalg.eigvalsh(_nearest_correlation(observed_matrix))
    )[::-1]

    # Marginal distribution per item, from observed responses only.
    marginals = []
    for j in range(n_items):
        column = data.values[:, j]
        column = column[column != MISSING]
        counts = np.bincount(column.astype(int), minlength=int(n_cat[j])).astype(float)
        marginals.append(counts / counts.sum())

    random_eigen = np.empty((n_iterations, n_items), dtype=float)
    for it in range(n_iterations):
        simulated = np.empty((n_persons, n_items), dtype=np.int16)
        for j in range(n_items):
            simulated[:, j] = rng.choice(
                int(n_cat[j]), size=n_persons, p=marginals[j]
            ).astype(np.int16)
        replicate = ResponseMatrix(
            values=simulated, item_ids=list(data.item_ids), n_categories=n_cat
        )
        matrix = polychoric_matrix(replicate).matrix
        random_eigen[it] = np.sort(
            np.linalg.eigvalsh(_nearest_correlation(matrix))
        )[::-1]

    reference = np.percentile(random_eigen, percentile, axis=0)
    mean = random_eigen.mean(axis=0)

    rows: list[EigenvalueRow] = []
    still_retaining = True
    retained = 0
    for c in range(n_items):
        passes = bool(observed_eigen[c] > reference[c])
        keep = still_retaining and passes
        if keep:
            retained += 1
        else:
            still_retaining = False
        rows.append(
            EigenvalueRow(
                component=c + 1,
                observed=float(observed_eigen[c]),
                random_mean=float(mean[c]),
                random_p95=float(reference[c]),
                retained=keep,
            )
        )

    if retained == 0:
        notes.append(
            "No component exceeded its random-data reference. Either the items "
            "share almost no common variance, or the sample is too small for "
            "any structure to emerge above noise."
        )
    if n_iterations < 50:
        notes.append(
            f"Only {n_iterations} random replications were run, so the "
            f"{percentile:g}th percentile reference is itself imprecise."
        )
    notes.append(
        "Parallel analysis answers how many components exceed chance, not how "
        "many are interpretable. A retained second component may still be a "
        "method artefact rather than a second construct."
    )

    return ParallelAnalysisResult(
        n_factors_retained=retained,
        eigenvalues=rows,
        n_iterations=n_iterations,
        percentile=percentile,
        seed=seed,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Velicer's MAP
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MapResult:
    """Velicer's minimum average partial, both exponents."""

    n_components_squared: int
    n_components_fourth: int
    average_squared: list[float]     # index m = m components partialled out
    average_fourth: list[float]
    notes: list[str] = field(default_factory=list)


def velicer_map(matrix: np.ndarray) -> MapResult:
    """Minimum average partial test (Velicer 1976; Velicer et al. 2000).

    Components are partialled out one at a time and the average squared
    off-diagonal *partial* correlation is recorded at each step. While the
    components being removed are common variance, the average falls; once they
    are removing item-specific variance it rises again. The minimum is the point
    at which only common variance has been taken out.

    The fourth-power variant is reported alongside the squared one because it
    weights the larger residual correlations more heavily and is less prone to
    under-extraction when the average is dominated by many near-zero residuals.
    The two disagreeing is informative in itself and both are returned.

    MAP is known to under-extract when factors are weakly defined - fewer than
    about four items each - which is stated in the notes rather than corrected
    for, because it cannot be corrected for from the matrix alone.
    """
    matrix = _nearest_correlation(np.asarray(matrix, dtype=float))
    p = matrix.shape[0]
    values, vectors = np.linalg.eigh(matrix)
    order = np.argsort(values)[::-1]
    values = np.clip(values[order], 0.0, None)
    vectors = vectors[:, order]

    off = ~np.eye(p, dtype=bool)

    squared: list[float] = []
    fourth: list[float] = []
    notes: list[str] = []

    for m in range(p):
        if m == 0:
            partial = matrix
        else:
            loadings = vectors[:, :m] * np.sqrt(values[:m])
            residual = matrix - loadings @ loadings.T
            diagonal = np.diag(residual)
            if np.any(diagonal <= 1e-10):
                # Nothing is left to partial: the remaining steps are undefined
                # rather than large, so the series stops here.
                notes.append(
                    f"The partial series stopped after {m - 1} components; "
                    "residual variance for at least one item reached zero."
                )
                break
            scale = np.sqrt(diagonal)
            partial = residual / np.outer(scale, scale)

        squared.append(float(np.mean(partial[off] ** 2)))
        fourth.append(float(np.mean(partial[off] ** 4)))

    if not squared:
        return MapResult(0, 0, [], [], ["MAP could not be computed."])

    notes.append(
        "MAP tends to under-extract when a factor is defined by fewer than "
        "about four items, and is not a substitute for inspecting the pattern "
        "of residual correlations."
    )
    if int(np.argmin(squared)) != int(np.argmin(fourth)):
        notes.append(
            "The squared and fourth-power criteria disagree, which usually "
            "means the second component is weak; treat the dimensionality as "
            "genuinely ambiguous."
        )

    return MapResult(
        n_components_squared=int(np.argmin(squared)),
        n_components_fourth=int(np.argmin(fourth)),
        average_squared=squared,
        average_fourth=fourth,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Bifactor-style variance decomposition
# --------------------------------------------------------------------------- #


def _varimax(loadings: np.ndarray, n_iter: int = 200, tol: float = 1e-8) -> np.ndarray:
    """Kaiser varimax rotation of a loading matrix.

    Unrotated principal components are ordered by variance, not by content: the
    second component of a two-block test is a *contrast* that loads positively on
    one block and negatively on the other, so items cannot be assigned to blocks
    by reading it directly. Rotating to simple structure recovers one column per
    block. The rotation is orthogonal, so communalities are unchanged; only the
    item-to-group assignment depends on it.
    """
    p, k = loadings.shape
    if k < 2:
        return loadings.copy()

    rotation = np.eye(k)
    previous = 0.0
    for _ in range(n_iter):
        rotated = loadings @ rotation
        gradient = loadings.T @ (
            rotated**3
            - rotated @ np.diag(np.sum(rotated**2, axis=0)) / p
        )
        u, s, vt = np.linalg.svd(gradient)
        rotation = u @ vt
        current = float(np.sum(s))
        if previous and current - previous < tol * current:
            break
        previous = current
    return loadings @ rotation


@dataclass(frozen=True)
class BifactorApproximation:
    """ECV, PUC and omega-hierarchical from an approximate bifactor pattern."""

    general_loadings: np.ndarray          # (n_items,)
    group_loadings: np.ndarray            # (n_items,), the retained group loading
    group_assignment: np.ndarray          # (n_items,), -1 when no group factor
    n_group_factors: int

    ecv: float
    puc: float
    omega_hierarchical: float
    omega_total: float
    notes: list[str] = field(default_factory=list)


def bifactor_approximation(
    matrix: np.ndarray, n_group_factors: int
) -> BifactorApproximation:
    """Schmid-Leiman-*style* decomposition by principal components.

    **This is an approximation, not a fitted bifactor model.** A proper bifactor
    solution requires a rotation criterion (bi-quartimin, or a target rotation
    from a theoretical grouping) and iterative estimation, neither of which is
    implemented here. What is implemented is:

    1. the general factor taken as the first principal component of the
       polychoric matrix;
    2. group factors taken as the leading principal components of the residual
       matrix ``R - g g'``, rotated to simple structure by varimax;
    3. each item assigned to the single group factor it loads on most strongly,
       with its other group loadings discarded.

    Step 3 imposes the bifactor pattern by fiat rather than deriving it. The
    consequences are real and one-directional: ECV computed this way is an
    upper-ish bound, because the first principal component absorbs some group
    variance that a fitted bifactor model would assign to group factors, and
    because discarding cross-loadings understates group-factor variance. The
    group assignment is data-driven, so PUC reflects the *empirical* clustering
    rather than the test blueprint - if a blueprint exists, PUC should be
    computed from it instead.

    Use these numbers to decide whether unidimensionality is *plausible enough*
    to proceed, not to make a claim about the strength of specific group factors.
    """
    matrix = _nearest_correlation(np.asarray(matrix, dtype=float))
    p = matrix.shape[0]
    notes = [
        (
            "ECV, PUC and omega-hierarchical come from a principal-component "
            "approximation to a bifactor pattern, not from a fitted bifactor "
            "model with a rotation criterion. They indicate whether a general "
            "factor dominates; they do not quantify specific group factors."
        ),
    ]

    values, vectors = np.linalg.eigh(matrix)
    order = np.argsort(values)[::-1]
    values = np.clip(values[order], 0.0, None)
    vectors = vectors[:, order]

    general = vectors[:, 0] * np.sqrt(values[0])
    # Sign is arbitrary in an eigenvector; orient so a positively-keyed test has
    # positive general loadings.
    if general.sum() < 0:
        general = -general

    group = np.zeros(p, dtype=float)
    assignment = np.full(p, -1, dtype=int)
    n_group = max(int(n_group_factors), 0)

    if n_group >= 2:
        # Items are clustered on the varimax-rotated components of R itself, not
        # of the residual. The residual of an F-factor test after one general
        # factor spans only F-1 dimensions, so rotating *it* cannot produce F
        # separable columns; rotating the full common space can.
        rotated = _varimax(vectors[:, :n_group] * np.sqrt(values[:n_group]))
        assignment = np.argmax(np.abs(rotated), axis=1)

        residual = matrix - np.outer(general, general)
        singleton = 0
        for f in range(n_group):
            members = np.flatnonzero(assignment == f)
            if members.size < 2:
                # One item cannot define a group factor; its residual variance
                # stays uniqueness rather than being promoted to a factor.
                singleton += int(members.size)
                continue
            block = residual[np.ix_(members, members)].copy()
            # Principal-axis style: the residual diagonal still holds each item's
            # uniqueness, and leaving it in would inflate the group loadings.
            off_block = np.abs(block - np.diag(np.diag(block)))
            np.fill_diagonal(block, off_block.max(axis=1))
            b_values, b_vectors = np.linalg.eigh(block)
            lead = int(np.argmax(b_values))
            lam = b_vectors[:, lead] * np.sqrt(max(float(b_values[lead]), 0.0))
            if lam.sum() < 0:
                lam = -lam
            group[members] = lam

        if singleton:
            notes.append(
                f"{singleton} item(s) were the only member of their cluster and "
                "contribute no group-factor variance, which raises ECV."
            )
    else:
        notes.append(
            "No group factors were requested, so PUC is 1 by construction and "
            "omega-hierarchical equals omega-total. These values carry no "
            "evidence about unidimensionality on their own."
        )

    general_variance = float(np.sum(general**2))
    group_variance = float(np.sum(group**2))
    common = general_variance + group_variance
    ecv = float(general_variance / common) if common > _FLOOR else float("nan")

    total_pairs = p * (p - 1) / 2.0
    if n_group >= 2 and total_pairs > 0:
        sizes = np.bincount(assignment, minlength=n_group).astype(float)
        within = float(np.sum(sizes * (sizes - 1) / 2.0))
        puc = float(1.0 - within / total_pairs)
    else:
        puc = 1.0

    uniqueness = np.clip(1.0 - general**2 - group**2, 0.0, None)
    general_sq = float(np.sum(general) ** 2)
    if n_group >= 2:
        group_sq = float(
            np.sum([np.sum(group[assignment == f]) ** 2 for f in range(n_group)])
        )
    else:
        group_sq = 0.0
    implied_variance = general_sq + group_sq + float(np.sum(uniqueness))

    if implied_variance > _FLOOR:
        omega_h = float(general_sq / implied_variance)
        omega_total = float((general_sq + group_sq) / implied_variance)
    else:
        omega_h = omega_total = float("nan")

    if puc > 0.80 and n_group >= 2:
        notes.append(
            f"PUC is {puc:.2f}. Above roughly 0.80 the general factor in any "
            "bifactor-style solution is close to the first factor of a "
            "unidimensional one, so a high ECV here is partly a consequence of "
            "the item grouping and not only of the data."
        )

    return BifactorApproximation(
        general_loadings=general,
        group_loadings=group,
        group_assignment=assignment,
        n_group_factors=n_group,
        ecv=ecv,
        puc=puc,
        omega_hierarchical=omega_h,
        omega_total=omega_total,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Unidimensionality, assembled
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UnidimensionalityReport:
    """Everything the platform knows about whether one trait is enough."""

    polychoric: PolychoricMatrix
    parallel: ParallelAnalysisResult
    map_test: MapResult
    bifactor: BifactorApproximation

    n_factors_parallel: int
    n_factors_map: int
    explained_common_variance: float
    percent_uncontaminated: float
    omega_hierarchical: float

    notes: list[str] = field(default_factory=list)

    JSON_PROPERTIES = ('essentially_unidimensional',)

    @property
    def essentially_unidimensional(self) -> bool | None:
        """Whether the conventional thresholds are all met.

        ``True`` when parallel analysis retains one factor, ECV exceeds 0.85 and
        omega-hierarchical exceeds 0.80 - the values commonly cited by Rodriguez,
        Reise & Haviland (2016) as supporting a single score. ``None`` when the
        evidence is mixed, which is a genuine outcome and not a failure: the
        report shows the components and the reader decides.
        """
        strong = (
            self.n_factors_parallel == 1
            and self.explained_common_variance > 0.85
            and self.omega_hierarchical > 0.80
        )
        weak = self.n_factors_parallel >= 2 and self.explained_common_variance < 0.70
        if strong:
            return True
        if weak:
            return False
        return None


def unidimensionality(
    data: ResponseMatrix,
    *,
    n_iterations: int = 100,
    percentile: float = 95.0,
    seed: int = 20260803,
) -> UnidimensionalityReport:
    """Assemble the dimensionality evidence for one response matrix.

    The three procedures are reported together because they fail differently:
    parallel analysis is sensitive to sample size, MAP under-extracts when
    factors are thin, and ECV/omega-hierarchical assume the bifactor pattern
    they are computed from. Agreement between them is what carries weight.
    """
    if data.n_items < 3:
        raise ValueError(
            f"dimensionality assessment needs at least 3 items, got {data.n_items}"
        )

    poly = polychoric_matrix(data)
    parallel = parallel_analysis(
        data, poly.matrix, n_iterations=n_iterations,
        percentile=percentile, seed=seed,
    )
    map_test = velicer_map(poly.matrix)

    # A Schmid-Leiman transformation of F correlated first-order factors under
    # one second-order factor yields a general factor plus F group factors, so
    # the group count is F rather than F - 1. One retained factor means there is
    # no group structure to model, and G = 1 is not an identified bifactor
    # pattern, so both collapse to zero group factors. Parallel analysis supplies
    # F rather than MAP, whose known under-extraction would flatter the general
    # factor.
    n_group = parallel.n_factors_retained if parallel.n_factors_retained >= 2 else 0
    bifactor = bifactor_approximation(poly.matrix, n_group)

    notes = list(poly.notes)
    if parallel.n_factors_retained != map_test.n_components_squared:
        notes.append(
            f"Parallel analysis retains {parallel.n_factors_retained} factor(s) "
            f"while MAP suggests {map_test.n_components_squared}. Disagreement "
            "between the two normally means a weak second dimension; inspect "
            "the loading pattern before treating either count as settled."
        )
    if data.n_persons < 250:
        notes.append(
            f"With {data.n_persons} respondents every procedure here is "
            "imprecise. Dimensionality decisions from samples this size should "
            "be treated as provisional."
        )
    notes.append(
        "Statistical dimensionality is not construct validity. A single factor "
        "here means the items covary as if driven by one thing; it does not "
        "establish that the thing is what the test claims to measure."
    )

    return UnidimensionalityReport(
        polychoric=poly,
        parallel=parallel,
        map_test=map_test,
        bifactor=bifactor,
        n_factors_parallel=parallel.n_factors_retained,
        n_factors_map=map_test.n_components_squared,
        explained_common_variance=bifactor.ecv,
        percent_uncontaminated=bifactor.puc,
        omega_hierarchical=bifactor.omega_hierarchical,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Local independence
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ItemPairStatistic:
    """Local-dependence evidence for one item pair."""

    index_a: int
    index_b: int
    item_a: str
    item_b: str

    q3: float
    q3_star: float
    ld_x2: float | None
    ld_df: int | None
    ld_signed_z: float | None
    flagged: bool


@dataclass(frozen=True)
class LocalIndependenceReport:
    pairs: list[ItemPairStatistic]
    q3_star_matrix: np.ndarray
    q3_mean: float
    critical_value: float | None
    alpha: float
    n_bootstrap: int
    seed: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> list[ItemPairStatistic]:
        return [p for p in self.pairs if p.flagged]


def local_independence(
    data: ResponseMatrix,
    items: list[ItemParameters],
    *,
    latent_sd: float = 1.0,
    alpha: float = 0.05,
    n_bootstrap: int = 200,
    seed: int = 20260803,
    n_points: int = 61,
    bound: float = 6.0,
) -> LocalIndependenceReport:
    """Yen's Q3 with a bootstrap null, plus Chen-Thissen standardised LD X2.

    **Q3.** For each respondent and item, the residual is the observed score
    minus the score the model expects given that respondent's posterior over
    theta. Under local independence those residuals are uncorrelated across
    items; a positive correlation for a pair means the pair shares variance the
    trait does not explain.

    **Why the residuals are correlated to begin with.** Q3 has a structural
    negative bias of roughly ``-1/(J-1)``: theta is estimated *from* the same
    responses, so the residuals are forced to sum to approximately zero across
    items and must correlate negatively on average. Q3* - Q3 minus the mean of
    all off-diagonal Q3 values - removes it. Both are reported.

    **Why there is no 0.2 cutoff.** The familiar ``|Q3| > 0.2`` rule is not
    scale-free. Christensen, Makransky & Horton (2017) show the critical value
    depends on test length, sample size and the item parameters themselves, and
    that a fixed cutoff over-flags short tests and under-flags long ones. This
    function instead builds the null empirically: ``n_bootstrap`` datasets are
    simulated from the *fitted* parameters, which satisfy local independence by
    construction, the Q3* matrix is recomputed for each, and the critical value
    is the ``1 - alpha`` quantile of the replication maxima of ``|Q3*|``. Taking
    the maximum controls the family-wise error rate over all pairs, which
    matters because a 20-item test has 190 of them. The critical value used is
    reported so a reader can see how far from 0.2 it is.

    **Limit of the bootstrap.** The item parameters are held fixed across
    replications rather than being re-estimated. Refitting B models would be
    prohibitively slow, and the omission means the null ignores parameter
    estimation error, making the critical value slightly too small and the test
    slightly liberal. This is recorded in the notes.

    **LD X2** (Chen & Thissen, 1997) compares the observed joint frequency table
    for a pair with the frequencies the model implies after integrating theta
    out. It is signed by whether the pair's observed association exceeds or falls
    short of the model's. It complements Q3 by detecting dependence that is not
    a simple linear residual correlation, though its reference distribution is
    only approximate when the item parameters were estimated from the same data.
    """
    if len(items) != data.n_items:
        raise ValueError(
            f"{len(items)} item parameter sets for {data.n_items} columns"
        )
    if data.n_items < 3:
        raise ValueError("Q3 needs at least 3 items to have a mean to correct by")

    nodes = np.linspace(-bound, bound, n_points)
    prior = np.exp(-0.5 * (nodes / latent_sd) ** 2)
    prior /= prior.sum()

    probs = [category_probabilities(p, nodes) for p in items]
    expected_by_node = [
        p @ np.arange(p.shape[1], dtype=float) for p in probs
    ]

    q3, q3_mean, q3_star = _q3_matrix(data.values, probs, prior, expected_by_node)

    critical, null_notes = _bootstrap_critical_value(
        items, probs, prior, expected_by_node,
        n_persons=data.n_persons,
        missing_mask=(data.values == MISSING),
        alpha=alpha, n_bootstrap=n_bootstrap, seed=seed,
    )

    ld = _ld_chi_square(data, probs, prior)

    pairs: list[ItemPairStatistic] = []
    for j in range(data.n_items):
        for m in range(j + 1, data.n_items):
            statistic, df, signed_z = ld[(j, m)]
            pairs.append(
                ItemPairStatistic(
                    index_a=j,
                    index_b=m,
                    item_a=items[j].item_id,
                    item_b=items[m].item_id,
                    q3=float(q3[j, m]),
                    q3_star=float(q3_star[j, m]),
                    ld_x2=statistic,
                    ld_df=df,
                    ld_signed_z=signed_z,
                    flagged=(
                        critical is not None
                        and abs(float(q3_star[j, m])) > critical
                    ),
                )
            )

    notes = list(null_notes)
    notes.append(
        f"The Q3* critical value is empirical, not the conventional 0.2. For "
        f"this test of {data.n_items} items and {data.n_persons} respondents it "
        + (f"came to {critical:.3f}." if critical is not None else "could not be computed.")
    )
    notes.append(
        "Q3's structural negative bias for this test length is about "
        f"{-1.0 / (data.n_items - 1):.3f}; the observed mean off-diagonal Q3 was "
        f"{q3_mean:.3f}. A large gap between the two suggests dependence spread "
        "across many pairs rather than concentrated in a few."
    )
    notes.append(
        "A flagged pair is not automatically a defect. Testlets sharing a "
        "stimulus are expected to be locally dependent; the question is whether "
        "the dependence was intended and modelled, not whether it exists."
    )

    positive = [p for p in pairs if p.flagged and p.q3_star > 0]
    if positive and len(pairs) and len([p for p in pairs if p.flagged]) > 1:
        strongest = max(positive, key=lambda p: p.q3_star)
        if strongest.q3_star > 0.4:
            notes.append(
                f"The dependence between {strongest.item_a} and "
                f"{strongest.item_b} (Q3* = {strongest.q3_star:.2f}) is strong "
                "enough to distort the theta estimates the residuals are taken "
                "from, which drags other pairs' Q3* downwards and can flag them "
                "negatively. Resolve the strongest pair first and recompute "
                "before interpreting the rest."
            )

    return LocalIndependenceReport(
        pairs=pairs,
        q3_star_matrix=q3_star,
        q3_mean=q3_mean,
        critical_value=critical,
        alpha=alpha,
        n_bootstrap=n_bootstrap,
        seed=seed,
        notes=notes,
    )


def _posterior(
    values: np.ndarray, probs: list[np.ndarray], prior: np.ndarray
) -> np.ndarray:
    """Each respondent's posterior over the quadrature nodes, from every item.

    Item-fit statistics deliberately exclude the item under scrutiny from the
    posterior they judge it against. Q3 must *not* do that: its whole logic - and
    the ``-1/(J-1)`` bias the Q3* correction removes - depends on theta being
    estimated from the complete response vector, the same vector whose residuals
    are then correlated.
    """
    log_lik = np.zeros((values.shape[0], prior.size), dtype=float)
    for j, p in enumerate(probs):
        column = values[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        log_p = np.log(np.clip(p, _FLOOR, None))
        log_lik[observed] += log_p[:, column[observed]].T

    joint = log_lik + np.log(np.clip(prior, 1e-300, None))[None, :]
    joint -= joint.max(axis=1, keepdims=True)
    post = np.exp(joint)
    return post / post.sum(axis=1, keepdims=True)


def _q3_matrix(
    values: np.ndarray,
    probs: list[np.ndarray],
    prior: np.ndarray,
    expected_by_node: list[np.ndarray],
) -> tuple[np.ndarray, float, np.ndarray]:
    """Q3, its off-diagonal mean, and the bias-corrected Q3*."""
    posterior = _posterior(values, probs, prior)
    n_items = values.shape[1]

    residual = np.full(values.shape, np.nan, dtype=float)
    for j in range(n_items):
        column = values[:, j]
        observed = column != MISSING
        expected = posterior[observed] @ expected_by_node[j]
        residual[observed, j] = column[observed].astype(float) - expected

    q3 = _pairwise_correlation(residual)
    off = ~np.eye(n_items, dtype=bool)
    q3_mean = float(np.nanmean(q3[off]))
    q3_star = q3 - q3_mean
    np.fill_diagonal(q3_star, 0.0)
    return q3, q3_mean, q3_star


def _pairwise_correlation(residual: np.ndarray) -> np.ndarray:
    """Pearson correlations over pairwise-complete rows, NaN marking missing."""
    n_items = residual.shape[1]
    out = np.eye(n_items, dtype=float)
    finite = np.isfinite(residual)
    for j in range(n_items):
        for m in range(j + 1, n_items):
            both = finite[:, j] & finite[:, m]
            if both.sum() < 3:
                out[j, m] = out[m, j] = np.nan
                continue
            a = residual[both, j]
            b = residual[both, m]
            sa = a.std()
            sb = b.std()
            if sa < _FLOOR or sb < _FLOOR:
                out[j, m] = out[m, j] = np.nan
                continue
            r = float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))
            out[j, m] = out[m, j] = r
    return out


def _simulate_from(
    items: list[ItemParameters], n_persons: int, rng: np.random.Generator
) -> np.ndarray:
    """Draw a response matrix from fitted parameters under local independence.

    This does not go through :func:`app.irt.simulate.simulate` because that takes
    a single model family for the whole test, while a bootstrap null has to
    reproduce exactly the parameters that were fitted, item by item.
    """
    theta = rng.normal(0.0, 1.0, size=n_persons)
    values = np.empty((n_persons, len(items)), dtype=np.int16)
    for j, params in enumerate(items):
        family = get_family(params.model)
        u = family.from_natural(params)
        p = family.probabilities(theta, u, params.n_categories)
        cumulative = np.cumsum(p, axis=1)
        draws = rng.random(n_persons)[:, None]
        values[:, j] = (draws > cumulative).sum(axis=1).astype(np.int16)
    np.clip(values, 0, None, out=values)
    for j, params in enumerate(items):
        np.clip(values[:, j], 0, params.n_categories - 1, out=values[:, j])
    return values


def _bootstrap_critical_value(
    items: list[ItemParameters],
    probs: list[np.ndarray],
    prior: np.ndarray,
    expected_by_node: list[np.ndarray],
    *,
    n_persons: int,
    missing_mask: np.ndarray,
    alpha: float,
    n_bootstrap: int,
    seed: int,
) -> tuple[float | None, list[str]]:
    """Family-wise critical value for max |Q3*| under the fitted model."""
    notes: list[str] = []
    if n_bootstrap < 1:
        notes.append(
            "No bootstrap replications were requested, so no pair can be "
            "flagged. Q3* values are reported without a reference distribution."
        )
        return None, notes

    rng = np.random.default_rng(seed)
    has_missing = bool(missing_mask.any())
    maxima = np.empty(n_bootstrap, dtype=float)

    for b in range(n_bootstrap):
        simulated = _simulate_from(items, n_persons, rng)
        if has_missing:
            # The missing pattern is reused so the null matches the real data's
            # per-pair sample sizes, which drive the sampling variance of Q3.
            simulated[missing_mask] = MISSING
        _, _, star = _q3_matrix(simulated, probs, prior, expected_by_node)
        maxima[b] = float(np.nanmax(np.abs(star)))

    critical = float(np.quantile(maxima, 1.0 - alpha))

    notes.append(
        f"The Q3* null distribution comes from {n_bootstrap} parametric "
        "bootstrap replications with the item parameters held fixed rather than "
        "re-estimated. Ignoring parameter estimation error makes the critical "
        "value slightly too small, so the test errs towards flagging."
    )
    if n_bootstrap < 100:
        notes.append(
            f"{n_bootstrap} replications give a coarse {1 - alpha:.0%} quantile; "
            "200 or more is preferable for a reported result."
        )
    return critical, notes


def _ld_chi_square(
    data: ResponseMatrix, probs: list[np.ndarray], prior: np.ndarray
) -> dict[tuple[int, int], tuple[float | None, int | None, float | None]]:
    """Chen-Thissen standardised LD X2 for every item pair.

    The model-expected joint table integrates theta out of the product of the two
    items' category probabilities - the product being exactly what local
    independence asserts. The statistic is standardised as ``(X2 - df) /
    sqrt(2 df)`` and signed by whether the observed association is stronger
    (positive) or weaker (negative) than the model implies, because the two have
    entirely different diagnostic meanings.
    """
    values = data.values
    n_items = data.n_items
    n_cat = data.n_categories.astype(int)
    out: dict[tuple[int, int], tuple[float | None, int | None, float | None]] = {}

    for j in range(n_items):
        for m in range(j + 1, n_items):
            both = (values[:, j] != MISSING) & (values[:, m] != MISSING)
            n_pair = int(both.sum())
            kj, km = int(n_cat[j]), int(n_cat[m])
            if n_pair < 10 * kj * km:
                out[(j, m)] = (None, None, None)
                continue

            observed = np.bincount(
                values[both, j].astype(int) * km + values[both, m].astype(int),
                minlength=kj * km,
            ).reshape(kj, km).astype(float)

            joint = np.einsum("q,qa,qb->ab", prior, probs[j], probs[m])
            joint /= joint.sum()
            expected = n_pair * joint

            usable = expected > _FLOOR
            statistic = float(
                np.sum((observed[usable] - expected[usable]) ** 2 / expected[usable])
            )
            df = (kj - 1) * (km - 1)
            z = (statistic - df) / np.sqrt(2.0 * df)

            sign = 1.0 if _table_correlation(observed) >= _table_correlation(expected) else -1.0
            out[(j, m)] = (statistic, df, float(sign * z))

    return out


def _table_correlation(table: np.ndarray) -> float:
    """Pearson correlation of the category codes implied by a frequency table."""
    total = table.sum()
    if total <= 0:
        return 0.0
    p = table / total
    a = np.arange(table.shape[0], dtype=float)
    b = np.arange(table.shape[1], dtype=float)
    ma = float(p.sum(axis=1) @ a)
    mb = float(p.sum(axis=0) @ b)
    va = float(p.sum(axis=1) @ (a - ma) ** 2)
    vb = float(p.sum(axis=0) @ (b - mb) ** 2)
    if va < _FLOOR or vb < _FLOOR:
        return 0.0
    cov = float((a - ma) @ p @ (b - mb))
    return cov / np.sqrt(va * vb)
