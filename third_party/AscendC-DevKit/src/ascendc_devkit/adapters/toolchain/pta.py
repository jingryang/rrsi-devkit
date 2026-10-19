"""L6 Adapters — PTA Toolchain: PyTorch Ascend adapter.

Generates torch.ops.custom registration code for AscendC operators,
enabling them to be called from PyTorch via the PTA interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.verification import BuildResult

if TYPE_CHECKING:
    from ascendc_devkit.domain.operator import OperatorSpec


@dataclass
class PTARegistration:
    """Generated PTA registration code and metadata."""
    source: str
    op_name: str
    namespace: str = "custom_ops"
    backend: str = "AscendC"

    @property
    def full_name(self) -> str:
        return f"torch.ops.{self.namespace}.{self.op_name}"

    @property
    def call_signature(self) -> str:
        return f"torch.ops.{self.namespace}.{self.op_name}(x)"


class PTAToolchain:
    """PyTorch Ascend adapter — generates torch.ops.custom boilerplate.

    Provides:
      - generate(): create torch.ops.custom registration source code
      - build(): compile registration code (stub, delegates to ops_compile)
    """

    _TEMPLATE = '''"""Auto-generated PTA registration for {op_name}."""
import torch
from torch.library import Library, impl

# Define the custom library
lib = Library("{namespace}", "DEF")

# Schema: define the operator signature
lib.define("{schema}")

@impl(lib, "{op_name}", "AscendC")
def {op_name}_impl(x: torch.Tensor) -> torch.Tensor:
    """AscendC backend implementation of {op_name}.

    This function is dispatched when the operator is called on NPU.
    The actual kernel is loaded via the AscendC runtime.
    """
    # TODO: Replace with actual kernel invocation after acop_runner integration
    from ascendc_runtime import run_kernel
    return run_kernel(
        kernel_name="{kernel_name}",
        inputs=[x],
        outputs=[],
    )

# Convenience function
def {op_name}(x: torch.Tensor) -> torch.Tensor:
    return torch.ops.{namespace}.{op_name}(x)
'''

    def generate(self, op_spec: OperatorSpec,
                 sources: dict[str, str] | None = None) -> str:
        """Generate torch.ops.custom registration code for an operator.

        Args:
            op_spec: Operator specification with name, signature, etc.
            sources: Optional generated kernel sources (for context).

        Returns:
            Python source code for PTA registration.
        """
        op_name = op_spec.name
        namespace = "custom_ops"
        kernel_name = f"{op_name}_kernel"

        # Infer schema from op_spec
        schema = self._infer_schema(op_spec)

        return self._TEMPLATE.format(
            op_name=op_name,
            namespace=namespace,
            schema=schema,
            kernel_name=kernel_name,
        )

    def build(self, pta_code: str, output_dir: Path) -> BuildResult:
        """Compile PTA registration code (stub — delegates to build system).

        Args:
            pta_code: Generated PTA registration source.
            output_dir: Directory to write output files.

        Returns:
            BuildResult indicating success or failure.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        pta_file = output_dir / "pta_registration.py"
        pta_file.write_text(pta_code)

        # Stub: PTA registration doesn't need separate compilation
        return BuildResult(
            passed=True,
            stdout=f"PTA registration written to {pta_file}",
            stubbed=True,
        )

    @staticmethod
    def _infer_schema(op_spec: OperatorSpec) -> str:
        """Infer the torch library schema from an operator spec."""
        op_name = op_spec.name
        # Default: element-wise unary op
        return f"{op_name}(Tensor x) -> Tensor"
