#
#     This file is part of rockit.
#
#     rockit -- Rapid Optimal Control Kit
#     Copyright (C) 2019 MECO, KU Leuven. All rights reserved.
#
#     Rockit is free software; you can redistribute it and/or
#     modify it under the terms of the GNU Lesser General Public
#     License as published by the Free Software Foundation; either
#     version 3 of the License, or (at your option) any later version.
#
#     Rockit is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#     Lesser General Public License for more details.
#
#     You should have received a copy of the GNU Lesser General Public
#     License along with CasADi; if not, write to the Free Software
#     Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
#

from casadi import MX, substitute, Function, vcat, depends_on, vertcat, jacobian, veccat, jtimes, hcat, linspace, DM, constpow, mtimes, vvcat, low, floor, hcat, horzcat, DM, is_equal
from .freetime import FreeTime
from .direct_method import DirectMethod
from .multiple_shooting import MultipleShooting
from .single_shooting import SingleShooting
from collections import defaultdict
from .casadi_helpers import DM2numpy, get_meta, merge_meta, HashDict, HashDefaultDict, HashOrderedDict
from contextlib import contextmanager
from collections import OrderedDict

import numpy as np
from numpy import nan

class Stage:
    """
        A stage is defined on a time domain and has particular system dynamics
        associated with it.

        Each stage has a transcription method associated with it.
    """
    def __init__(self, parent=None, t0=0, T=1, clone=False):
        """Create an Optimal Control Problem stage.
        
        Only call this constructer when you need abstract stages,
        ie stages that are not associated with an :obj:`~rockit.ocp.Ocp`.
        For other uses, see :obj:`~rockit.stage.Stage.stage`.

        Parameters
        ----------
        parent : float or :obj:`~rockit.stage.Stage`, optional
            Parent Stage to which 
            Default: None
        t0 : float or :obj:`~rockit.freetime.FreeTime`, optional
            Starting time of the stage
            Default: 0
        T : float or :obj:`~rockit.freetime.FreeTime`, optional
            Total horizon of the stage
            Default: 1

        Examples
        --------

        >>> stage = Stage()
        """
        self.states = []
        self.qstates = []
        self.controls = []
        self.algebraics = []
        self.parameters = defaultdict(list)
        self.variables = defaultdict(list)

        self._master = parent.master if parent else None
        self.parent = parent

        self._param_vals = HashDict()
        self._state_der = HashDict()
        self._state_next = HashDict()
        self._alg = []
        self._constraints = defaultdict(list)
        self._objective = 0
        self._initial = HashOrderedDict()

        self._placeholders = HashDict()
        self._placeholder_callbacks = HashDict()
        self._offsets = HashDict()
        self._inf_inert = HashOrderedDict()
        self._inf_der = HashOrderedDict()
        self._t = MX.sym('t')
        self._stages = []
        self._method = DirectMethod()
        self._t0 = t0
        self._T = T
        self._public_T = self._create_placeholder_expr(0, 'T')
        self._public_t0 = self._create_placeholder_expr(0, 't0')
        self._tf = self.T + self.t0
        if not clone:
            self._check_free_time()
    
    @property
    def master(self):
        return self._master

    @property
    def t(self):
        return self._t

    @property
    def T(self):
        return self._public_T

    @property
    def t0(self):
        return self._public_t0

    @property
    def tf(self):
        return self._tf

    def _check_free_time(self):
        if isinstance(self._t0, FreeTime):
            init = self._t0.T_init
            self.set_t0(self.variable())
            self.set_initial(self._t0, init)
        if isinstance(self._T, FreeTime):
            init = self._T.T_init
            self.set_T(self.variable())
            self.subject_to(self._T>=0)
            self.set_initial(self._T, init)

    def set_t0(self, t0):
        self._t0 = t0

    def set_T(self, T):
        self._T = T

    def stage(self, template=None, **kwargs):
        """Create a new :obj:`~rockit.stage.Stage` and add it as to the :obj:`~rockit.ocp.Ocp`.

        Parameters
        ----------
        template : :obj:`~rockit.stage.Stage`, optional
            A stage to copy from. Will not be modified.
        t0 : float or :obj:`~rockit.freetime.FreeTime`, optional
            Starting time of the stage
            Default: 0
        T : float or :obj:`~rockit.freetime.FreeTime`, optional
            Total horizon of the stage
            Default: 1

        Returns
        -------
        s : :obj:`~rockit.stage.Stage`
            New stage
        """
        if template:
            s = template.clone(self, clone=True, **kwargs)
        else:
            s = Stage(self, **kwargs)
        self._stages.append(s)
        self._set_transcribed(False)
        return s

    def state(self, n_rows=1, n_cols=1, quad=False):
        """Create a state.
        You must supply a derivative for the state with :obj:`~rockit.stage.Stage.set_der`

        Parameters
        ----------
        n_rows : int, optional
            Number of rows
            Default: 1
        n_cols : int, optional
            Number of columns
            Default: 1

        Returns
        -------
        s : :obj:`~casadi.MX`
            A CasADi symbol representing a state

        Examples
        --------

        Defining the first-order ODE :  :math:`\dot{x} = -x`
        
        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        >>> ocp.set_initial(x, sin(ocp.t)) # Optional: give initial guess
        """
        import numpy
        # Create a placeholder symbol with a dummy name (see #25)
        x = MX.sym("x"+str(int(numpy.random.rand()*10000)), n_rows, n_cols)
        if quad:
            self.qstates.append(x)
        else:
            self.states.append(x)
        self._set_transcribed(False)
        return x

    def algebraic(self, n_rows=1, n_cols=1):
        """Create an algebraic variable
        You must supply an algebraic relation with:obj:`~rockit.stage.Stage.set_alg`

        Parameters
        ----------
        n_rows : int, optional
            Number of rows
            Default: 1
        n_cols : int, optional
            Number of columns
            Default: 1

        Returns
        -------
        s : :obj:`~casadi.MX`
            A CasADi symbol representing an algebraic variable
        """
        # Create a placeholder symbol with a dummy name (see #25)
        z = MX.sym("z", n_rows, n_cols)
        self.algebraics.append(z)
        self._set_transcribed(False)
        return z

    def variable(self, n_rows=1, n_cols=1, grid = ''):
        # Create a placeholder symbol with a dummy name (see #25)
        v = MX.sym("v"+str(np.random.random(1)), n_rows, n_cols)
        self.variables[grid].append(v)
        self._set_transcribed(False)
        return v

    def parameter(self, n_rows=1, n_cols=1, grid = ''):
        """
        Create a parameter
        """
        # Create a placeholder symbol with a dummy name (see #25)
        p = MX.sym("p", n_rows, n_cols)
        self.parameters[grid].append(p)
        self._set_transcribed(False)
        return p

    def control(self, n_rows=1, n_cols=1, order=0):
        """Create a control signal to optimize for

        A control signal is parametrized as a piecewise polynomial.
        By default (order=0), it is piecewise constant.

        Parameters
        ----------
        n_rows : int, optional
            Number of rows
        n_cols : int, optional
            Number of columns
        order : int, optional
            Order of polynomial. order=0 denotes a constant.
        Returns
        -------
        s : :obj:`~casadi.MX`
            A CasADi symbol representing a control signal

        Examples
        --------

        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> u = ocp.control()
        >>> ocp.set_der(x, u)
        >>> ocp.set_initial(u, sin(ocp.t)) # Optional: give initial guess
        """

        if order >= 1:
            u = self.state(n_rows, n_cols)
            helper_u = self.control(n_rows=n_rows, n_cols=n_cols, order=order - 1)
            self.set_der(u, helper_u)
            return u

        u = MX.sym("u", n_rows, n_cols)
        self.controls.append(u)
        self._set_transcribed(False)
        return u

    def set_value(self, parameter, value):
        if self.master is not None and self.master.is_transcribed:
            self._method.set_value(self, self.master._method, parameter, value)            
        else:
            self._param_vals[parameter] = value

    def set_initial(self, var, value):
        assert "opti" not in str(var)
        self._initial[var] = value
        if self.master is not None and self.master.is_transcribed:
            self._method.set_initial(self, self.master._method, self._initial)

    def set_der(self, state, der):
        """Assign a right-hand side to a state derivative

        Parameters
        ----------
        state : `~casadi.MX`
            A CasADi symbol created with :obj:`~rockit.stage.Stage.state`.
        der : `~casadi.MX`
            A CasADi symbolic expression of the same size as `state`

        Examples
        --------

        Defining the first-order ODE :  :math:`\dot{x} = -x`
        
        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        """
        self._set_transcribed(False)
        assert not self._state_next
        self._state_der[state] = der

    def set_next(self, state, next):
        """Assign an update rule for a discrete state

        Parameters
        ----------
        state : `~casadi.MX`
            A CasADi symbol created with :obj:`~rockit.stage.Stage.state`.
        next : `~casadi.MX`
            A CasADi symbolic expression of the same size as `state`

        Examples
        --------

        Defining the first-order difference equation :  :math:`x^{+} = -x`
        
        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_next(x, -x)
        """
        self._set_transcribed(False)
        self._state_next[state] = next
        assert not self._state_der

    def add_alg(self, constr):
        self._set_transcribed(False)
        self._alg.append(constr)

    def der(self, expr):
        if depends_on(expr, self.u):
            raise Exception("Dependency on controls not supported yet for stage.der")
        ode = self._ode()
        return jtimes(expr, self.x, ode(x=self.x, u=self.u, z=self.z, p=vertcat(self.p, self.v), t=self.t)["ode"])

    def integral(self, expr, grid='inf'):
        """Compute an integral or a sum

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            An expression to integrate over the state time domain (from t0 to tf=t0+T)
        grid : str
            Possible entries:
                inf: the integral is performed using the integrator defined for the stage
                control: the integral is evaluated as a sum on the control grid (start of each control interval),
                         with each term of the sum weighted with the time duration of the interval.
                         Note that the final state is not included in this definition
        """
        if grid=='inf':
            I = self.state(quad=True)
            self.set_der(I, expr)
            return self.at_tf(I)
        else:
            return self._create_placeholder_expr(expr, 'integral_control')

    def sum(self, expr, grid='inf'):
        """Compute a sum

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            An expression to integrate over the state time domain (from t0 to tf=t0+T)
        grid : str
            Possible entries:
                inf: the integral is performed using the integrator defined for the stage
                control: the integral is evaluated as a sum on the control grid (start of each control interval)
                         Note that the final state is not included in this definition
        """
        return self._create_placeholder_expr(expr, 'sum_control')

    def offset(self, expr, offset):
        """Get the value of a signal at control interval current+offset

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            An expression
        offset : (positive or negative) integer
        """
        if int(offset)!=offset:
            raise Exception("Integer expected")
        offset = int(offset)
        ret = MX.sym("offset", expr.shape)
        self._offsets[ret] = (expr, offset)
        return ret

    def next(self, expr):
        """Get the value of a signal at the next control interval

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            An expression
        """
        return self.offset(expr, 1)

    def inf_inert(self, expr):
        """Specify that expression should be treated as constant for grid=inf constraints
        """
        ret = MX.sym("inert", MX(expr).sparsity())
        self._inf_inert[ret] = expr
        return ret

    def inf_der(self, expr):
        """Specify that expression should be treated as constant for grid=inf constraints
        """
        ret = MX.sym("der", MX(expr).sparsity())
        self._inf_der[ret] = expr
        return ret

    def prev(self, expr):
        """Get the value of a signal at the previous control interval

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            An expression
        """
        return self.offset(expr, -1)

    def clear_constraints(self):
        """
        Remove any previously declared constraints from the problem
        """
        self._set_transcribed(False)
        self._constraints = defaultdict(list)

    def subject_to(self, constr, grid=None,include_first=True,include_last=True,meta=None):
        """Adds a constraint to the problem

        Parameters
        ----------
        constr : :obj:`~casadi.MX`
            A constrained expression. It should be a symbolic expression that depends
            on decision variables and features a comparison `==`, `<=`, `=>`.

            If `constr` is a signal (:obj:`~rockit.stage.Stage.is_signal`, depends on time)
            a path-constraint is assumed: it should hold over the entire stage horizon.

            If `constr` is not a signal (e.g. :obj:`~rockit.stage.Stage.at_t0`/:obj:`~rockit.stage.Stage.at_tf` was applied on states),
            a boundary constraint is assumed.
        grid : str
            A string containing the type of grid to constrain the problem
            Possible entries: 
                control: constraint at control interval edges
                inf: use mathematical guarantee for the whole control interval (only possible for polynomials of states and controls)
                integrator: constrain at integrator edges
                integrator_roots: constrain at integrator roots (e.g. collocation points excluding 0)

        Examples
        --------

        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        >>> ocp.subject_to( x <= 3)             # path constraint
        >>> ocp.subject_to( ocp.at_t0(x) == 0)  # boundary constraint
        >>> ocp.subject_to( ocp.at_tf(x) == 0)  # boundary constraint
        """
        self._set_transcribed(False)
        #import ipdb; ipdb.set_trace()
        if grid is None:
            grid = 'control' if self.is_signal(constr) else 'point'
        if grid not in ['point', 'control', 'inf', 'integrator', 'integrator_roots']:
            raise Exception("Invalid argument")
        if self.is_signal(constr):
            if grid == 'point':
                raise Exception("Got a signal expression for grid 'point'.")
        else:
            if grid != 'point': 
                raise Exception("Expected signal expression since grid '" + grid + "' was given.")
        
        args = {"grid": grid, "include_last": include_last, "include_first": include_first}
        self._constraints[grid].append((constr, get_meta(meta), args))

    def at_t0(self, expr):
        """Evaluate a signal at the start of the horizon

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            A symbolic expression that may depend on states and controls

        Returns
        -------
        s : :obj:`~casadi.MX`
            A CasADi symbol representing an evaluation at `t0`.

        Examples
        --------

        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        >>> ocp.subject_to( ocp.at_t0(sin(x)) == 0)
        """
        return self._create_placeholder_expr(expr, 'at_t0')

    def at_tf(self, expr):
        """Evaluate a signal at the end of the horizon

        Parameters
        ----------
        expr : :obj:`~casadi.MX`
            A symbolic expression that may depend on states and controls

        Returns
        -------
        s : :obj:`~casadi.MX`
            A CasADi symbol representing an evaluation at `tf`.

        Examples
        --------

        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        >>> ocp.subject_to( ocp.at_tf(sin(x)) == 0)
        """
        return self._create_placeholder_expr(expr, 'at_tf')

    def add_objective(self, term):
        """Add a term to the objective of the Optimal Control Problem

        Parameters
        ----------
        term : :obj:`~casadi.MX`
            A symbolic expression that may not depend directly on states and controls.
            Use :obj:`~rockit.stage.Stage.at_t0`/:obj:`~rockit.stage.Stage.at_tf`/:obj:`~rockit.stage.Stage.integral`
            to eliminate the time-dependence of states and controls.

        Examples
        --------

        >>> ocp = Ocp()
        >>> x = ocp.state()
        >>> ocp.set_der(x, -x)
        >>> ocp.add_objective( ocp.at_tf(x) )    # Mayer term
        >>> ocp.add_objective( ocp.integral(x) ) # Lagrange term

        """
        self._set_transcribed(False)
        self._objective = self._objective + term

    def method(self, method):
        """Specify the transcription method

        Note that, for multi-stage problems, each stages can have a different method specification.

        Parameters
        ----------
        method : :obj:`~casadi.MX`
            Instance of a subclass of :obj:`~rockit.direct_method.DirectMethod`.
            Will not be modified

        Examples
        --------

        >>> ocp = Ocp()
        >>> ocp.method(MultipleShooting())
        """
        from copy import deepcopy
        self._set_transcribed(False)
        template = self._method
        self._method = deepcopy(method)
        self._method.inherit(template)

    @property
    def objective(self):
        return self._objective

    @property
    def x(self):
        return vvcat(self.states)

    @property
    def xq(self):
        return vvcat(self.qstates)

    @property
    def u(self):
        if len(self.controls)==0: return MX(0, 1)
        return vvcat(self.controls)

    @property
    def z(self):
        return vvcat(self.algebraics)

    @property
    def p(self):
        return vvcat(self.parameters['']+self.parameters['control'])

    @property
    def v(self):
        return vvcat(self.variables['']+self.variables['control'])

    @property
    def nx(self):
        return self.x.numel()

    @property
    def nz(self):
        return self.z.numel()

    @property
    def nu(self):
        return self.u.numel()

    @property
    def np(self):
        return self.p.numel()

    @property
    def gist(self):
        """Obtain an expression packing all information needed to obtain value/sample

        The composition of this array may vary between rockit versions

        Returns
        -------
        :obj:`~casadi.MX` column vector

        """
        return self.master.gist

    def is_signal(self, expr):
        """Does the expression represent a signal (does it depend on time)?

        Returns
        -------
        res : bool

        """
 
        return depends_on(expr, vertcat(self.x, self.u, self.z, self.t, vcat(self.variables['control']+self.variables['states']), vvcat(self._inf_der.keys())))

    def _create_placeholder_expr(self, expr, callback_name):
        r = MX.sym("r_" + callback_name, MX(expr).sparsity())
        self._placeholders[r] = expr
        self._placeholder_callbacks[r] = callback_name
        if self.master is not None:
            self.master._transcribed_placeholders.mark_dirty()
        return r

    def _transcribe_placeholders(self, method, placeholders):
        for k, v in self._placeholders.items():
            if k not in placeholders:
                callback = getattr(method, 'fill_placeholders_' + self._placeholder_callbacks[k])
                placeholders[k] = callback(self, v)

    # Internal methods
    def _ode(self):
        ode = veccat(*[self._state_der[k] for k in self.states])
        quad = veccat(*[self._state_der[k] for k in self.qstates])
        alg = veccat(*self._alg)
        return Function('ode', [self.x, self.u, self.z, vertcat(self.p, self.v), self.t], [ode, alg, quad], ["x", "u", "z", "p", "t"], ["ode","alg","quad"])

    # Internal methods
    def _diffeq(self):
        next = veccat(*[self._state_next[k] for k in self.states])
        quad = veccat(*[self._state_next[k] for k in self.qstates])

        dt = MX(1,1)
        return Function('ode', [self.x, self.u, vertcat(self.p, self.v), self.t, dt], [next, MX(), quad, MX(0, 1), MX()], ["x0", "u", "p", "t0", "DT"], ["xf","poly_coeff","qf","zf","poly_coeff_z"])

    def _expr_apply(self, expr, **kwargs):
        """
        Substitute placeholder symbols with actual decision variables,
        or expressions involving decision variables
        """
        subst_from, subst_to = self._get_subst_set(**kwargs)
        temp = [(f,t) for f,t in zip(subst_from, subst_to) if f is not None and not f.is_empty() and t is not None]
        subst_from = [e[0] for e in temp]
        subst_to = [e[1] for e in temp]
        return substitute([MX(expr)], subst_from, subst_to)[0]

    def _get_subst_set(self, **kwargs):
        subst_from = []
        subst_to = []
        if "sub" in kwargs:
            subst_from += kwargs["sub"][0]
            subst_to += kwargs["sub"][1]
        if "t" in kwargs:
            subst_from.append(self.t)
            subst_to.append(kwargs["t"])
        if "x" in kwargs:
            subst_from.append(self.x)
            subst_to.append(kwargs["x"])
        if "z" in kwargs:
            subst_from.append(self.z)
            subst_to.append(kwargs["z"])
        if "t0" in kwargs and kwargs["t0"] is not None:
            subst_from.append(self.t0)
            subst_to.append(kwargs["t0"])
        if "T" in kwargs and kwargs["T"] is not None:
            subst_from.append(self.T)
            subst_to.append(kwargs["T"])
        if "xq" in kwargs:
            subst_from.append(self.xq)
            subst_to.append(kwargs["xq"])
        if "u" in kwargs:
            subst_from.append(self.u)
            subst_to.append(kwargs["u"])
        if "p" in kwargs and self.parameters['']:
            p = veccat(*self.parameters[''])
            subst_from.append(p)
            subst_to.append(kwargs["p"])
        if "p_control" in kwargs and self.parameters['control']:
            p = veccat(*self.parameters['control'])
            subst_from.append(p)
            subst_to.append(kwargs["p_control"])
        if "v" in kwargs and self.variables['']:
            v = veccat(*self.variables[''])
            subst_from.append(v)
            subst_to.append(kwargs["v"])
        if "v_control" in kwargs and self.variables['control']:
            v = veccat(*self.variables['control'])
            subst_from.append(v)
            subst_to.append(kwargs["v_control"])
        if "v_states" in kwargs and self.variables['states']:
            v = veccat(*self.variables['states'])
            subst_from.append(v)
            subst_to.append(kwargs["v_states"])
        return (subst_from, subst_to)

    _constr_apply = _expr_apply

    def _set_transcribed(self, val):
        if self.master:
            self.master._is_transcribed = val

    @property
    def is_transcribed(self):
        if self.master:
            return self.master._is_transcribed
        else:
            return False

    def _transcribe_recurse(self, pass_nr=1, **kwargs):
        if self._method is not None:
            if self is self.master:
                self._method.main_transcribe(self, pass_nr=pass_nr, **kwargs)
            self._method.transcribe(self, pass_nr=pass_nr, **kwargs)
        else:
            print("master",self)

        for s in self._stages:
            s._transcribe_recurse(pass_nr=pass_nr, **kwargs)

    def _placeholders_transcribe_recurse(self, placeholders):
        if self._method is not None:
            self._method.transcribe_placeholders(self, placeholders)

        for s in self._stages:
            s._placeholders_transcribe_recurse(placeholders)

    def clone(self, parent, **kwargs):
        ret = Stage(parent, **kwargs)
        from copy import copy, deepcopy

        # Placeholders need to be updated
        subst_from = list(self._placeholders.keys())
        subst_to = []
        for k in self._placeholders.keys():
            if is_equal(k, self.T):  # T and t0 already have new placeholder symbols
                subst_to.append(ret.T)
            elif is_equal(k, self.t0):
                subst_to.append(ret.t0)
            else:
                subst_to.append(MX.sym(k.name(), k.sparsity()))
        for k_old, k_new in zip(subst_from, subst_to):
            ret._placeholder_callbacks[k_new] = self._placeholder_callbacks[k_old]
            ret._placeholders[k_new] = self._placeholders[k_old]

        ret.states = copy(self.states)
        ret.controls = copy(self.controls)
        ret.algebraics = copy(self.algebraics)
        ret.parameters = deepcopy(self.parameters)
        ret.variables = deepcopy(self.variables)

        ret._offsets = deepcopy(self._offsets)
        ret._param_vals = copy(self._param_vals)
        ret._state_der = copy(self._state_der)
        ret._alg = copy(self._alg)
        ret._state_next = copy(self._state_next)
        constr_types = self._constraints.keys()
        orig = []
        for k in constr_types:
            orig.extend([c for c, _, _ in self._constraints[k]])
        n_constr = len(orig)
        orig.append(self._objective)
        orig.extend(self._initial.keys())
        res = substitute(orig, subst_from, subst_to)
        ret._objective = res[n_constr]
        r = res[:n_constr]
        ret._constraints = defaultdict(list)
        for k in constr_types:
            v = self._constraints[k]
            ret._constraints[k] = list(zip(r, [merge_meta(m, get_meta()) for _, m, _ in v], [d for _, _, d in v]))
            r = r[len(v):]

        ret._initial = HashOrderedDict(zip(res[n_constr+1:], self._initial.values()))
        ret._check_free_time()

        if "T" not in kwargs:
            ret._T = copy(self._T)
        if "t0" not in kwargs:
            ret._t0 = copy(self._t0)
        ret._t = self.t
        ret._method = deepcopy(self._method)

        ret._is_transcribed = False
        return ret

    def iter_stages(self, include_self=False):
        if include_self:
            yield self
        for s in self._stages:
            for e in s.iter_stages(include_self=True): yield e

    @staticmethod
    def _parse_grid(grid):
        include_last = True
        include_first = True
        if grid.startswith('-'):
            grid = grid[1:]
            include_last = False
        if grid.endswith('-'):
            grid = grid[:-1]
            include_last = False
        return grid, include_first, include_last

    def sample(self, expr, grid='control', **kwargs):
        """Sample expression symbolically on a given grid.

        Parameters
        ----------
        expr : :obj:`casadi.MX`
            Arbitrary expression containing states, controls, ...
        grid : `str`
            At which points in time to sample, options are
            'control' or 'integrator' (at integrator discretization
            level) or 'integrator_roots'.
        refine : int, optional
            Refine grid by evaluation the polynomal of the integrater at
            intermediate points ("refine" points per interval).

        Returns
        -------
        time : :obj:`casadi.MX`
            Time from zero to final time, same length as res
        res : :obj:`casadi.MX`
            Symbolically evaluated expression at points in time vector.

        Examples
        --------
        Assume an ocp with a stage is already defined.

        >>> sol = ocp.solve()
        >>> tx, xs = sol.sample(x, grid='control')
        """
        self.master._transcribe()
        placeholders = self.master.placeholders_transcribed
        grid, include_first, include_last = self._parse_grid(grid)
        kwargs["include_first"] = include_first
        kwargs["include_last"] = include_last
        if grid == 'control':
            time, res = self._grid_control(self, expr, grid, **kwargs)
        elif grid == 'control-':
            time, res = self._grid_control(self, expr, grid, include_last=False, **kwargs)
        elif grid == 'integrator':
            if 'refine' in kwargs:
                time, res = self._grid_intg_fine(self, expr, grid, **kwargs)
            else:
                time, res = self._grid_integrator(self, expr, grid, **kwargs)
        elif grid == 'integrator_roots':
            time, res = self._grid_integrator_roots(self, expr, grid, **kwargs)
        else:
            msg = "Unknown grid option: {}\n".format(grid)
            msg += "Options are: 'control' or 'integrator' with an optional extra refine=<int> argument."
            raise Exception(msg)

        return placeholders(time), placeholders(res)

    def _grid_control(self, stage, expr, grid, include_first=True, include_last=True):
        """Evaluate expression at (N + 1) control points."""
        sub_expr = []
        ks = list(range(1, stage._method.N))
        if include_first:
            ks = [0]+ks
        if include_last:
            ks = ks+[-1]
        for k in ks:
            try:
                r = stage._method.eval_at_control(stage, expr, k)
            except IndexError as e:
                r = DM.nan(MX(expr).shape)
            sub_expr.append(r)
        res = hcat(sub_expr)
        time = stage._method.control_grid
        return time, res

    def _grid_integrator(self, stage, expr, grid, include_first=True, include_last=True):
        """Evaluate expression at (N*M + 1) integrator discretization points."""
        sub_expr = []
        time = []
        assert include_first
        for k in range(stage._method.N):
            for l in range(stage._method.M):
                sub_expr.append(stage._method.eval_at_integrator(stage, expr, k, l))
            time.append(stage._method.integrator_grid[k])
        if include_last:
            sub_expr.append(stage._method.eval_at_control(stage, expr, -1))
        return vcat(time), hcat(sub_expr)


    def _grid_integrator_roots(self, stage, expr, grid, include_first=True, include_last=True):
        """Evaluate expression at integrator roots."""
        sub_expr = []
        tr = []
        assert include_first
        assert include_last
        for k in range(stage._method.N):
            for l in range(stage._method.M):
                for j in range(stage._method.xr[k][l].shape[1]):
                    sub_expr.append(stage._method.eval_at_integrator_root(stage, expr, k, l, j))
                tr.extend(stage._method.tr[k][l])
        return hcat(tr).T, hcat(sub_expr)

    def _grid_intg_fine(self, stage, expr, grid, refine, include_first=True, include_last=True):
        """Evaluate expression at extra fine integrator discretization points."""
        assert include_first
        assert include_last
        if stage._method.poly_coeff is None:
            msg = "No polynomal coefficients for the {} integration method".format(stage._method.intg)
            raise Exception(msg)
        N, M = stage._method.N, stage._method.M

        expr_f = Function('expr', [stage.x, stage.z, stage.u], [expr])

        time = stage._method.control_grid
        total_time = []
        sub_expr = []
        for k in range(N):
            t0 = time[k]
            dt = (time[k+1]-time[k])/M
            tlocal = linspace(MX(0), dt, refine + 1)
            assert tlocal.is_column()
            ts = tlocal[:-1,:]
            for l in range(M):
                total_time.append(t0+tlocal[:-1])
                coeff = stage._method.poly_coeff[k * M + l]
                tpower = hcat([constpow(ts,i) for i in range(coeff.shape[1])]).T
                if stage._method.poly_coeff_z:
                    coeff_z = stage._method.poly_coeff_z[k * M + l]
                    tpower_z = hcat([constpow(ts,i) for i in range(coeff_z.shape[1])]).T
                    z = mtimes(coeff_z,tpower_z)
                else:
                    z = nan
                sub_expr.append(stage._method.eval_at_integrator(stage, expr_f(mtimes(coeff,tpower), z, stage._method.U[k]), k, l))
                t0+=dt

        ts = tlocal[-1,:]
        total_time.append(time[k+1])
        tpower = hcat([constpow(ts,i) for i in range(coeff.shape[1])]).T
        if stage._method.poly_coeff_z:
            tpower_z = hcat([constpow(ts,i) for i in range(coeff_z.shape[1])]).T
            z = mtimes(coeff_z,tpower_z)
        else:
            z = nan

        sub_expr.append(stage._method.eval_at_integrator(stage, expr_f(mtimes(stage._method.poly_coeff[-1],tpower), z, stage._method.U[-1]), k, l))

        return vcat(total_time), hcat(sub_expr)

    def value(self, expr, *args, **kwargs):
        """Get the value of an (non-signal) expression.

        Parameters
        ----------
        expr : :obj:`casadi.MX`
            Arbitrary expression containing no signals (states, controls) ...
        """
        self.master._transcribe()
        placeholders = self.master.placeholders_transcribed
        return placeholders(self._method.eval(self, expr))

    def discrete_system(self):
        """Hack"""
        return self._method.discrete_system(self)

    def sampler(self, *args):
        """Returns a function that samples given expressions


        This function has two modes of usage:
        1)  sampler(exprs)  -> Python function
        2)  sampler(name, exprs, options) -> CasADi function

        Parameters
        ----------
        exprs : :obj:`casadi.MX` or list of :obj:`casadi.MX`
            List of arbitrary expression containing states, controls, ...
        name : `str`
            Name for CasADi Function
        options : dict, optional
            Options for CasADi Function

        Returns
        -------
        (gist, t) -> output
        mode 1 : Python Function
            Symbolically evaluated expression at points in time vector.
        mode 2 : :obj:`casadi.Function`
            Time from zero to final time, same length as res
        """

        numpy = True
        name = 'sampler'
        options = {}
        exprs = []
        ret_list = True
        if isinstance(args[0],str):
            name = args[0]
            exprs = args[1]
            if len(args)>=3: options = args[2]
            numpy = False
        else:
            exprs = args[0]
        if not isinstance(exprs, list):
            ret_list = False
            exprs = [exprs]

        self.master._transcribe()
        t = MX.sym('t')

        """Evaluate expression at extra fine integrator discretization points."""
        if self._method.poly_coeff is None:
            msg = "No polynomal coefficients for the {} integration method".format(self._method.intg)
            raise Exception(msg)
        N, M = self._method.N, self._method.M

        expr_f = Function('expr', [self.x, self.z, self.u], exprs)

        time = vcat(self._method.integrator_grid)
        k = low(self._method.control_grid, t)        
        i = low(time, t)
        ti = time[i]
        tlocal = t-ti

        for c in self._method.poly_coeff:
            assert c.shape == self._method.poly_coeff[0].shape

        coeffs = hcat(self._method.poly_coeff)
        s = self._method.poly_coeff[0].shape[1]
        coeff = coeffs[:,(i*s+DM(range(s)).T)]

        tpower = constpow(tlocal,range(s))
        if self._method.poly_coeff_z:
            for c in self._method.poly_coeff_z:
                assert c.shape == self._method.poly_coeff_z[0].shape
            coeffs_z = hcat(self._method.poly_coeff_z)
            s_z = self._method.poly_coeff_z[0].shape[1]
            coeff_z = coeffs_z[:,i*s_z+DM(range(s_z)).T]
            tpower_z = constpow(tlocal,range(s_z))
            z = mtimes(coeff_z,tpower_z)
        else:
            z = nan

        Us = hcat(self._method.U)
        f = Function(name,[self.gist, t],expr_f.call([mtimes(coeff,tpower), z, Us[:,k]]), options)

        if numpy:
            def wrapper(gist, t):
                """
                Parameters
                ----------
                gist : float vector
                    The gist of the solution, provided from `sol.gist` or
                    the evaluation of `ocp.gist`
                t : float or float vector
                    time or time-points to sample at

                Returns
                -------
                :obj:`np.array`

                """
                tdim = None if isinstance(t, float) or isinstance(t, int) or len(t.shape)==0 else DM(t).numel()
                t = DM(t)
                if t.is_column(): t = t.T
                res = f.call([gist, t])
                if ret_list:
                    return [DM2numpy(r, expr_f.size_out(i), tdim) for i,r in enumerate(res)]
                else:
                    return DM2numpy(res[0], expr_f.size_out(0), tdim)
            return wrapper
        else:
            return f
