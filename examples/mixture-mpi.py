"""Demonstrate simple gas mixture with Pyrometheus."""

__copyright__ = """
Copyright (C) 2020 University of Illinois Board of Trustees
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import logging
import numpy as np
import pyopencl as cl
import pyopencl.tools as cl_tools
from functools import partial

from meshmode.array_context import PyOpenCLArrayContext
from meshmode.dof_array import thaw
from meshmode.mesh import BTAG_ALL, BTAG_NONE  # noqa
from grudge.eager import EagerDGDiscretization
from grudge.shortcuts import make_visualizer


from mirgecom.euler import euler_operator
from mirgecom.simutil import (
    inviscid_sim_timestep,
    sim_checkpoint,
    generate_and_distribute_mesh,
    ExactSolutionMismatch
)
from mirgecom.io import make_init_message
from mirgecom.mpi import mpi_entry_point

from mirgecom.integrators import rk4_step
from mirgecom.steppers import advance_state
from mirgecom.boundary import PrescribedBoundary
from mirgecom.initializers import MixtureInitializer
from mirgecom.eos import PyrometheusMixture

import cantera
import pyrometheus as pyro

logger = logging.getLogger(__name__)


@mpi_entry_point
def main(ctx_factory=cl.create_some_context, use_leap=False):
    """Drive example."""
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)
    actx = PyOpenCLArrayContext(queue,
            allocator=cl_tools.MemoryPool(cl_tools.ImmediateAllocator(queue)))

    dim = 3
    nel_1d = 16
    order = 3
    exittol = 10.0
    t_final = 0.002
    current_cfl = 1.0
    velocity = np.zeros(shape=(dim,))
    velocity[:dim] = 1.0
    current_dt = .001
    current_t = 0
    constant_cfl = False
    nstatus = 1
    nviz = 1
    rank = 0
    checkpoint_t = current_t
    current_step = 0
    if use_leap:
        from leap.rk import RK4MethodBuilder
        timestepper = RK4MethodBuilder("state")
    else:
        timestepper = rk4_step
    box_ll = -5.0
    box_ur = 5.0
    error_state = 0

    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()

    from meshmode.mesh.generation import generate_regular_rect_mesh
    generate_mesh = partial(generate_regular_rect_mesh, a=(box_ll,) * dim,
                            b=(box_ur,) * dim, nelements_per_axis=(nel_1d,) * dim)
    local_mesh, global_nelements = generate_and_distribute_mesh(comm, generate_mesh)
    local_nelements = local_mesh.nelements

    discr = EagerDGDiscretization(
        actx, local_mesh, order=order, mpi_communicator=comm
    )
    nodes = thaw(actx, discr.nodes())
    casename = "uiuc_mixture"

    # Pyrometheus initialization
    from mirgecom.mechanisms import get_mechanism_cti
    mech_cti = get_mechanism_cti("uiuc")
    sol = cantera.Solution(phase_id="gas", source=mech_cti)
    pyrometheus_mechanism = pyro.get_thermochem_class(sol)(actx.np)

    nspecies = pyrometheus_mechanism.num_species
    eos = PyrometheusMixture(pyrometheus_mechanism)

    y0s = np.zeros(shape=(nspecies,))
    for i in range(nspecies-1):
        y0s[i] = 1.0 / (10.0 ** (i + 1))
    spec_sum = sum([y0s[i] for i in range(nspecies-1)])
    y0s[nspecies-1] = 1.0 - spec_sum

    # Mixture defaults to STP (p, T) = (1atm, 300K)
    initializer = MixtureInitializer(dim=dim, nspecies=nspecies,
                                     massfractions=y0s, velocity=velocity)

    boundaries = {BTAG_ALL: PrescribedBoundary(initializer)}
    nodes = thaw(actx, discr.nodes())
    current_state = initializer(x_vec=nodes, eos=eos)

    visualizer = make_visualizer(discr)
    initname = initializer.__class__.__name__
    eosname = eos.__class__.__name__
    init_message = make_init_message(dim=dim, order=order,
                                     nelements=local_nelements,
                                     global_nelements=global_nelements,
                                     dt=current_dt, t_final=t_final, nstatus=nstatus,
                                     nviz=nviz, cfl=current_cfl,
                                     constant_cfl=constant_cfl, initname=initname,
                                     eosname=eosname, casename=casename)
    if rank == 0:
        logger.info(init_message)

    get_timestep = partial(inviscid_sim_timestep, discr=discr, t=current_t,
                           dt=current_dt, cfl=current_cfl, eos=eos,
                           t_final=t_final, constant_cfl=constant_cfl)

    def my_rhs(t, state):
        return euler_operator(discr, cv=state, t=t,
                              boundaries=boundaries, eos=eos)

    def my_checkpoint(step, t, dt, state):
        global checkpoint_t
        checkpoint_t = t
        return sim_checkpoint(discr, visualizer, eos, cv=state,
                              exact_soln=initializer, vizname=casename, step=step,
                              t=t, dt=dt, nstatus=nstatus, nviz=nviz,
                              exittol=exittol, constant_cfl=constant_cfl, comm=comm)

    try:
        (current_step, current_t, current_state) = \
            advance_state(rhs=my_rhs, timestepper=timestepper,
                checkpoint=my_checkpoint,
                get_timestep=get_timestep, state=current_state,
                t=current_t, t_final=t_final)
    except ExactSolutionMismatch as ex:
        error_state = 1
        current_step = ex.step
        current_t = ex.t
        current_state = ex.state

    if current_t != checkpoint_t:  # This check because !overwrite
        if rank == 0:
            logger.info("Checkpointing final state ...")
        my_checkpoint(current_step, t=current_t,
                      dt=(current_t - checkpoint_t),
                      state=current_state)

    if current_t - t_final < 0:
        error_state = 1

    if error_state:
        raise ValueError("Simulation did not complete successfully.")


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    main(use_leap=False)

# vim: foldmethod=marker
