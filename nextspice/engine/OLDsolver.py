from .matrix import DenseMatrix, LUSolver, SolverOptions

class Simulator:
    def __init__(self, circuit, options=None):
        self.circuit = circuit
        self.options = options or SolverOptions()
        self.solver = LUSolver(self.options)
        self.extra_var_map = {}
        self.dim = 0

    def _prepare_structure(self):
        node_map = self.circuit.node_mgr.mapping
        node_count = max(node_map.values()) if node_map else 0
        
        curr_extra_idx = node_count
        self.extra_var_map = {}
        for el in self.circuit.elements:
            if el.extra_vars > 0:
                self.extra_var_map[el] = curr_extra_idx
                curr_extra_idx += el.extra_vars
        
        self.dim = curr_extra_idx
        return self.dim

    def solve_op(self):
        dim = self._prepare_structure()
        if dim == 0: return None

        matrix = DenseMatrix(dim, dim)
        rhs = [0.0] * dim

        for el in self.circuit.elements:
            extra_idx = self.extra_var_map.get(el)
            # 使用你的 stamp 簽名
            el.stamp(matrix, rhs, extra_idx=extra_idx, circuit=self.circuit)

        matrix_orig = matrix.copy()
        status = self.solver.factorize(matrix)
        
        if status == "SUCCESS":
            return self.solver.solve(matrix, rhs, matrix_orig)
        else:
            print(f"OP Failed: {status}")
            return None

    def _solve_basic(self, m_lu, b):
        """用於迭代改進的基礎求解"""
        return self.solver.solve(m_lu, b).x
