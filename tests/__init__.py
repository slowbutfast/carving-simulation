"""
Test package initialization for carving-simulation.
Enforces a 4 GB address space ceiling to prevent runaway 3D carving simulations from locking the container.
"""
import resource

MAX_AS = 4 * 1024 * 1024 * 1024  # 4 GB
try:
    resource.setrlimit(resource.RLIMIT_AS, (MAX_AS, MAX_AS))
except Exception:
    pass
