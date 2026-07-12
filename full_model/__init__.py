"""Full-range model driver subpackage for wave-explorer.

Rebuilds the ASAP model spectrum over the full observed wavelength range for a
single star by reusing ASAP's unmodified ``gen_spec`` on a tiny "corner" grid
restricted to the bracketing best-fit nodes. See ``driver.compute_full_model``.
"""
