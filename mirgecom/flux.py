""":mod:`mirgecom.flux` provides inter-facial flux routines.

Numerical Flux Routines
^^^^^^^^^^^^^^^^^^^^^^^
.. autofunction:: lfr_flux
"""

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


def lfr_flux(q_tpair, compute_flux, normal, lam):
    r"""Compute Lax-Friedrichs/Rusanov flux after [Hesthaven_2008]_, Section 6.6.

    The Lax-Friedrichs/Rusanov flux is calculated as:

    .. math::

        f_{\mathtt{LFR}} = \frac{1}{2}(\mathbf{f}^{+} + \mathbf{f}^{-}) \cdot
        \hat{n} + \frac{\lambda}{2}(q^{-} - q^{+}),

    where $f^-, f^+$, and $q^-, q^+$ are the fluxes and scalar solution components on
    the interior and the exterior of the face on which the LFR flux is to be
    calculated. The The face normal is $\hat{n}$, and $\lambda$ is the user-supplied
    jump term coefficient.

    Parameters
    ^^^^^^^^^^
    q_tpair:

        Trace pair (grudge.symbolic.TracePair) for the face upon which flux
        calculation is to be performed

    compute_flux:

        function should return ambient dim-vector fluxes given *q* values

    normal: numpy.ndarray

        object array of :class:`meshmode.dof_array.DOFArray` with outward-pointing
        normals

    lam: :class:`meshmode.dof_array.DOFArray`

        lambda parameter for Lax-Friedrichs/Rusanov flux

    Returns
    ^^^^^^^
    numpy.ndarray

        object array of meshmode.dof_array.DOFArray with the Lax-Friedrichs/Rusanov
        flux.
    """
    flux_avg = 0.5*(compute_flux(q_tpair.int)
                    + compute_flux(q_tpair.ext))
    return flux_avg @ normal - 0.5*lam*(q_tpair.ext - q_tpair.int)