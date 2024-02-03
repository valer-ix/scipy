"""HiGHS Linear Optimization Methods

Interface to HiGHS linear optimization software.
https://highs.dev/

.. versionadded:: 1.5.0

References
----------
.. [1] Q. Huangfu and J.A.J. Hall. "Parallelizing the dual revised simplex
           method." Mathematical Programming Computation, 10 (1), 119-142,
           2018. DOI: 10.1007/s12532-017-0130-5

"""

from enum import Enum
import numpy as np
from ._optimize import OptimizeWarning, OptimizeResult
from warnings import warn
from ._highs._highs_wrapper import _highs_wrapper
from scipy.sparse import csc_matrix, vstack, issparse

import scipy.optimize._highs.highspy._highs as _h
import scipy.optimize._highs.highspy._highs.simplex_constants as simpc


class HighsStatusMapping:
    """Class to map HiGHS statuses to SciPy-like Return Codes and Messages"""

    class SciPyRC(Enum):
        """Return codes like SciPy's for solvers"""

        OPTIMAL = 0
        ITERATION_LIMIT = 1
        INFEASIBLE = 2
        UNBOUNDED = 3
        NUMERICAL = 4

    def __init__(self):
        self.highs_to_scipy = {
            _h.HighsModelStatus.kNotset: (
                self.SciPyRC.NUMERICAL,
                "Not set",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kLoadError: (
                self.SciPyRC.NUMERICAL,
                "Load Error",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kModelError: (
                self.SciPyRC.INFEASIBLE,
                "Model Error",
                "The problem is infeasible.",
            ),
            _h.HighsModelStatus.kPresolveError: (
                self.SciPyRC.NUMERICAL,
                "Presolve Error",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kSolveError: (
                self.SciPyRC.NUMERICAL,
                "Solve Error",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kPostsolveError: (
                self.SciPyRC.NUMERICAL,
                "Postsolve Error",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kModelEmpty: (
                self.SciPyRC.NUMERICAL,
                "Model Empty",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kOptimal: (
                self.SciPyRC.OPTIMAL,
                "Optimal",
                "Optimization terminated successfully.",
            ),
            _h.HighsModelStatus.kInfeasible: (
                self.SciPyRC.INFEASIBLE,
                "Infeasible",
                "The problem is infeasible.",
            ),
            _h.HighsModelStatus.kUnboundedOrInfeasible: (
                self.SciPyRC.NUMERICAL,
                "Unbounded or Infeasible",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kUnbounded: (
                self.SciPyRC.UNBOUNDED,
                "Unbounded",
                "The problem is unbounded.",
            ),
            _h.HighsModelStatus.kObjectiveBound: (
                self.SciPyRC.NUMERICAL,
                "Objective Bound",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kObjectiveTarget: (
                self.SciPyRC.NUMERICAL,
                "Objective Target",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kTimeLimit: (
                self.SciPyRC.ITERATION_LIMIT,
                "Time Limit",
                "Time limit reached.",
            ),
            _h.HighsModelStatus.kIterationLimit: (
                self.SciPyRC.ITERATION_LIMIT,
                "Iteration Limit",
                "Iteration limit reached.",
            ),
            _h.HighsModelStatus.kUnknown: (
                self.SciPyRC.NUMERICAL,
                "Unknown",
                "Serious numerical difficulties encountered.",
            ),
            _h.HighsModelStatus.kSolutionLimit: (
                self.SciPyRC.NUMERICAL,
                "Solution Limit",
                "Serious numerical difficulties encountered.",
            ),
        }

    def get_scipy_status(self, highs_status, highs_message):
        """Converts HiGHS status and message to SciPy-like status and messages"""
        if highs_status is None or highs_message is None:
            print(f"Highs Status: {highs_status}, Message: {highs_message}")
            return (
                self.SciPyRC.NUMERICAL.value,
                "HiGHS did not provide a status code. (HiGHS Status None: None)",
            )

        scipy_status_enum, message_prefix, scipy_message = self.highs_to_scipy.get(
            _h.HighsModelStatus(highs_status),
            (
                self.SciPyRC.NUMERICAL,
                "Unknown HiGHS Status",
                "The HiGHS status code was not recognized.",
            ),
        )
        full_scipy_message = (
            f"{scipy_message} (HiGHS Status {int(highs_status)}: {highs_message})"
        )
        return scipy_status_enum.value, full_scipy_message


def _replace_inf(x):
    # Replace `np.inf` with kHighsInf
    infs = np.isinf(x)
    with np.errstate(invalid="ignore"):
        x[infs] = np.sign(x[infs]) * _h.kHighsInf
    return x


class SimplexStrategy(Enum):
    DANTZIG = "dantzig"
    DEVEX = "devex"
    STEEPEST_DEVEX = "steepest-devex"  # highs min, choose
    STEEPEST = "steepest"  # highs max

    def to_highs_enum(self):
        mapping = {
            SimplexStrategy.DANTZIG: simpc.SimplexEdgeWeightStrategy.kSimplexEdgeWeightStrategyDantzig.value,
            SimplexStrategy.DEVEX: simpc.SimplexEdgeWeightStrategy.kSimplexEdgeWeightStrategyDevex.value,
            SimplexStrategy.STEEPEST_DEVEX: simpc.SimplexEdgeWeightStrategy.kSimplexEdgeWeightStrategyChoose.value,
            SimplexStrategy.STEEPEST: simpc.SimplexEdgeWeightStrategy.kSimplexEdgeWeightStrategySteepestEdge.value,
        }
        return mapping.get(self)


def convert_to_highs_enum(option, option_str, choices_enum, default_value):
    if option is None:
        return choices_enum[default_value.upper()].to_highs_enum()
    try:
        enum_value = choices_enum[option.upper()]
    except KeyError:
        warn(
            f"Option {option_str} is {option}, but only values in "
            f"{[e.value for e in choices_enum]} are allowed. Using default: "
            f"{default_value}.",
            OptimizeWarning,
            stacklevel=3,
        )
        enum_value = choices_enum[default_value.upper()]
    return enum_value.to_highs_enum()


def _linprog_highs(lp, solver, time_limit=None, presolve=True,
                   disp=False, maxiter=None,
                   dual_feasibility_tolerance=None,
                   primal_feasibility_tolerance=None,
                   ipm_optimality_tolerance=None,
                   simplex_dual_edge_weight_strategy=None,
                   mip_rel_gap=None,
                   mip_max_nodes=None,
                   **unknown_options):
    r"""
    Solve the following linear programming problem using one of the HiGHS
    solvers:

    User-facing documentation is in _linprog_doc.py.

    Parameters
    ----------
    lp :  _LPProblem
        A ``scipy.optimize._linprog_util._LPProblem`` ``namedtuple``.
    solver : "ipm" or "simplex" or None
        Which HiGHS solver to use.  If ``None``, "simplex" will be used.

    Options
    -------
    maxiter : int
        The maximum number of iterations to perform in either phase. For
        ``solver='ipm'``, this does not include the number of crossover
        iterations.  Default is the largest possible value for an ``int``
        on the platform.
    disp : bool
        Set to ``True`` if indicators of optimization status are to be printed
        to the console each iteration; default ``False``.
    time_limit : float
        The maximum time in seconds allotted to solve the problem; default is
        the largest possible value for a ``double`` on the platform.
    presolve : bool
        Presolve attempts to identify trivial infeasibilities,
        identify trivial unboundedness, and simplify the problem before
        sending it to the main solver. It is generally recommended
        to keep the default setting ``True``; set to ``False`` if presolve is
        to be disabled.
    dual_feasibility_tolerance : double
        Dual feasibility tolerance.  Default is 1e-07.
        The minimum of this and ``primal_feasibility_tolerance``
        is used for the feasibility tolerance when ``solver='ipm'``.
    primal_feasibility_tolerance : double
        Primal feasibility tolerance.  Default is 1e-07.
        The minimum of this and ``dual_feasibility_tolerance``
        is used for the feasibility tolerance when ``solver='ipm'``.
    ipm_optimality_tolerance : double
        Optimality tolerance for ``solver='ipm'``.  Default is 1e-08.
        Minimum possible value is 1e-12 and must be smaller than the largest
        possible value for a ``double`` on the platform.
    simplex_dual_edge_weight_strategy : str (default: None)
        Strategy for simplex dual edge weights. The default, ``None``,
        automatically selects one of the following.

        ``'dantzig'`` uses Dantzig's original strategy of choosing the most
        negative reduced cost.

        ``'devex'`` uses the strategy described in [15]_.

        ``steepest`` uses the exact steepest edge strategy as described in
        [16]_.

        ``'steepest-devex'`` begins with the exact steepest edge strategy
        until the computation is too costly or inexact and then switches to
        the devex method.

        Currently, using ``None`` always selects ``'steepest-devex'``, but this
        may change as new options become available.

    mip_max_nodes : int
        The maximum number of nodes allotted to solve the problem; default is
        the largest possible value for a ``HighsInt`` on the platform.
        Ignored if not using the MIP solver.
    unknown_options : dict
        Optional arguments not used by this particular solver. If
        ``unknown_options`` is non-empty, a warning is issued listing all
        unused options.

    Returns
    -------
    sol : dict
        A dictionary consisting of the fields:

            x : 1D array
                The values of the decision variables that minimizes the
                objective function while satisfying the constraints.
            fun : float
                The optimal value of the objective function ``c @ x``.
            slack : 1D array
                The (nominally positive) values of the slack,
                ``b_ub - A_ub @ x``.
            con : 1D array
                The (nominally zero) residuals of the equality constraints,
                ``b_eq - A_eq @ x``.
            success : bool
                ``True`` when the algorithm succeeds in finding an optimal
                solution.
            status : int
                An integer representing the exit status of the algorithm.

                ``0`` : Optimization terminated successfully.

                ``1`` : Iteration or time limit reached.

                ``2`` : Problem appears to be infeasible.

                ``3`` : Problem appears to be unbounded.

                ``4`` : The HiGHS solver ran into a problem.

            message : str
                A string descriptor of the exit status of the algorithm.
            nit : int
                The total number of iterations performed.
                For ``solver='simplex'``, this includes iterations in all
                phases. For ``solver='ipm'``, this does not include
                crossover iterations.
            crossover_nit : int
                The number of primal/dual pushes performed during the
                crossover routine for ``solver='ipm'``.  This is ``0``
                for ``solver='simplex'``.
            ineqlin : OptimizeResult
                Solution and sensitivity information corresponding to the
                inequality constraints, `b_ub`. A dictionary consisting of the
                fields:

                residual : np.ndnarray
                    The (nominally positive) values of the slack variables,
                    ``b_ub - A_ub @ x``.  This quantity is also commonly
                    referred to as "slack".

                marginals : np.ndarray
                    The sensitivity (partial derivative) of the objective
                    function with respect to the right-hand side of the
                    inequality constraints, `b_ub`.

            eqlin : OptimizeResult
                Solution and sensitivity information corresponding to the
                equality constraints, `b_eq`.  A dictionary consisting of the
                fields:

                residual : np.ndarray
                    The (nominally zero) residuals of the equality constraints,
                    ``b_eq - A_eq @ x``.

                marginals : np.ndarray
                    The sensitivity (partial derivative) of the objective
                    function with respect to the right-hand side of the
                    equality constraints, `b_eq`.

            lower, upper : OptimizeResult
                Solution and sensitivity information corresponding to the
                lower and upper bounds on decision variables, `bounds`.

                residual : np.ndarray
                    The (nominally positive) values of the quantity
                    ``x - lb`` (lower) or ``ub - x`` (upper).

                marginals : np.ndarray
                    The sensitivity (partial derivative) of the objective
                    function with respect to the lower and upper
                    `bounds`.

            mip_node_count : int
                The number of subproblems or "nodes" solved by the MILP
                solver. Only present when `integrality` is not `None`.

            mip_dual_bound : float
                The MILP solver's final estimate of the lower bound on the
                optimal solution. Only present when `integrality` is not
                `None`.

            mip_gap : float
                The difference between the final objective function value
                and the final dual bound, scaled by the final objective
                function value. Only present when `integrality` is not
                `None`.

    Notes
    -----
    The result fields `ineqlin`, `eqlin`, `lower`, and `upper` all contain
    `marginals`, or partial derivatives of the objective function with respect
    to the right-hand side of each constraint. These partial derivatives are
    also referred to as "Lagrange multipliers", "dual values", and
    "shadow prices". The sign convention of `marginals` is opposite that
    of Lagrange multipliers produced by many nonlinear solvers.

    References
    ----------
    .. [15] Harris, Paula MJ. "Pivot selection methods of the Devex LP code."
            Mathematical programming 5.1 (1973): 1-28.
    .. [16] Goldfarb, Donald, and John Ker Reid. "A practicable steepest-edge
            simplex algorithm." Mathematical Programming 12.1 (1977): 361-371.
    """
    if unknown_options:
        message = (f"Unrecognized options detected: {unknown_options}. "
                   "These will be passed to HiGHS verbatim.")
        warn(message, OptimizeWarning, stacklevel=3)

    # Map options to HiGHS enum values
    simplex_dual_edge_weight_strategy_enum = convert_to_highs_enum(
        simplex_dual_edge_weight_strategy,
        "simplex_dual_edge_weight_strategy",
        choices_enum=SimplexStrategy,
        default_value="dantzig",
    )

    c, A_ub, b_ub, A_eq, b_eq, bounds, x0, integrality = lp

    lb, ub = bounds.T.copy()  # separate bounds, copy->C-cntgs
    # highs_wrapper solves LHS <= A*x <= RHS, not equality constraints
    with np.errstate(invalid="ignore"):
        lhs_ub = -np.ones_like(b_ub)*np.inf  # LHS of UB constraints is -inf
    rhs_ub = b_ub  # RHS of UB constraints is b_ub
    lhs_eq = b_eq  # Equality constraint is inequality
    rhs_eq = b_eq  # constraint with LHS=RHS
    lhs = np.concatenate((lhs_ub, lhs_eq))
    rhs = np.concatenate((rhs_ub, rhs_eq))

    if issparse(A_ub) or issparse(A_eq):
        A = vstack((A_ub, A_eq))
    else:
        A = np.vstack((A_ub, A_eq))
    A = csc_matrix(A)

    options = {
        'presolve': presolve,
        'sense': _h.ObjSense.kMinimize,
        'solver': solver,
        'time_limit': time_limit,
        # 'highs_debug_level': _h.kHighs, # TODO
        'dual_feasibility_tolerance': dual_feasibility_tolerance,
        'ipm_optimality_tolerance': ipm_optimality_tolerance,
        'log_to_console': disp,
        'mip_max_nodes': mip_max_nodes,
        'output_flag': disp,
        'primal_feasibility_tolerance': primal_feasibility_tolerance,
        'simplex_dual_edge_weight_strategy': simplex_dual_edge_weight_strategy_enum,
        'simplex_strategy': simpc.kSimplexStrategyDual.value,
        # 'simplex_crash_strategy': simpc.SimplexCrashStrategy.kSimplexCrashStrategyOff,
        'ipm_iteration_limit': maxiter,
        'simplex_iteration_limit': maxiter,
        'mip_rel_gap': mip_rel_gap,
    }
    options.update(unknown_options)

    # np.inf doesn't work; use very large constant
    rhs = _replace_inf(rhs)
    lhs = _replace_inf(lhs)
    lb = _replace_inf(lb)
    ub = _replace_inf(ub)

    if integrality is None or np.sum(integrality) == 0:
        integrality = np.empty(0)
    else:
        integrality = np.array(integrality)

    res = _highs_wrapper(c, A.indptr, A.indices, A.data, lhs, rhs,
                         lb, ub, integrality.astype(np.uint8), options)

    # HiGHS represents constraints as lhs/rhs, so
    # Ax + s = b => Ax = b - s
    # and we need to split up s by A_ub and A_eq
    if 'slack' in res:
        slack = res['slack']
        con = np.array(slack[len(b_ub):])
        slack = np.array(slack[:len(b_ub)])
    else:
        slack, con = None, None

    # lagrange multipliers for equalities/inequalities and upper/lower bounds
    if 'lambda' in res:
        lamda = res['lambda']
        marg_ineqlin = np.array(lamda[:len(b_ub)])
        marg_eqlin = np.array(lamda[len(b_ub):])
        marg_upper = np.array(res['marg_bnds'][1, :])
        marg_lower = np.array(res['marg_bnds'][0, :])
    else:
        marg_ineqlin, marg_eqlin = None, None
        marg_upper, marg_lower = None, None

    # this needs to be updated if we start choosing the solver intelligently

    # Convert to scipy-style status and message
    highs_mapper = HighsStatusMapping()
    highs_status = res.get("status", None)
    highs_message = res.get("message", None)
    status, message = highs_mapper.get_scipy_status(highs_status, highs_message)

    def is_valid_x(val):
        if isinstance(val, np.ndarray):
            if val.dtype == object and None in val:
                return False
        return val is not None

    x = np.array(res["x"]) if "x" in res and is_valid_x(res["x"]) else None

    sol = {'x': x,
           'slack': slack,
           'con': con,
           'ineqlin': OptimizeResult({
               'residual': slack,
               'marginals': marg_ineqlin,
           }),
           'eqlin': OptimizeResult({
               'residual': con,
               'marginals': marg_eqlin,
           }),
           'lower': OptimizeResult({
               'residual': None if x is None else x - lb,
               'marginals': marg_lower,
           }),
           'upper': OptimizeResult({
               'residual': None if x is None else ub - x,
               'marginals': marg_upper
            }),
           'fun': res.get('fun'),
           'status': status,
           'success': res['status'] == _h.HighsModelStatus.kOptimal,
           'message': message,
           'nit': res.get('simplex_nit', 0) or res.get('ipm_nit', 0),
           'crossover_nit': res.get('crossover_nit'),
           }

    if np.any(x) and integrality is not None:
        sol.update({
            'mip_node_count': res.get('mip_node_count', 0),
            'mip_dual_bound': res.get('mip_dual_bound', 0.0),
            'mip_gap': res.get('mip_gap', 0.0),
        })

    return sol
