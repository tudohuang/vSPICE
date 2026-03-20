import math

class SolverOptions:
    """工業級求解器配置：參數化所有數值邊界"""
    def __init__(self, 
                 pivot_abs_tol=1e-20,   # 絕對主元容限
                 pivot_rel_tol=1e-13,   # 相對主元容限 (Scaled)
                 refine_steps=3,        # 迭代改進次數
                 stagnation_ratio=0.99, # 迭代停滯判定
                 zero_tol=1e-24,        # 零值判定
                 eps=1e-30):            # 防止除以零
        self.pivot_abs_tol = pivot_abs_tol
        self.pivot_rel_tol = pivot_rel_tol
        self.refine_steps = refine_steps
        self.stagnation_ratio = stagnation_ratio
        self.zero_tol = zero_tol
        self.eps = eps

class SolverResult:
    """結構化診斷報告：為「病態電路」提供深度分析數據"""
    def __init__(self, x=None, status="SUCCESS", error_msg="", 
                 residual=0.0, backward_error=0.0, 
                 iterations=0, cond_hint=1.0, row=None, pivot_val=0.0):
        self.x = x
        self.status = status
        self.error_msg = error_msg
        self.residual = residual      # Scaled Forward Residual
        self.backward_error = backward_error
        self.iterations = iterations
        self.condition_hint = cond_hint    # max_pivot / min_pivot
        self.row = row                # 出錯的行號 (用於映射回電路節點)
        self.pivot_val = pivot_val    # 出錯時的主元值

    def __repr__(self):
        return (f"SolverResult(status={self.status}, res={self.residual:.2e}, "
                f"back_err={self.backward_error:.2e}, cond={self.cond_hint:.2e}, iter={self.iterations})")

class DenseMatrix:
    """工業級數據容器：支援 Scaled Partial Pivoting"""
    def __init__(self, rows, cols, is_complex=False):
        self.rows, self.cols = rows, cols
        self.is_complex = is_complex
        self.dtype = complex if is_complex else float
        self.data = [self.dtype(0.0)] * (rows * cols)

    def copy(self):
        new_mat = DenseMatrix(self.rows, self.cols, self.is_complex)
        new_mat.data = self.data[:]
        return new_mat

    def add_at(self, r, c, val):
        if r < 0 or c < 0: return # Node 0 忽略 [cite: 68]
        self.data[r * self.cols + c] += val

    def get_row_norm(self, r):
        """計算行範數：工業級 Scaling 的基石"""
        row_off = r * self.cols
        return max(abs(self.data[row_off + c]) for c in range(self.cols))

    def get_matrix_norm(self):
        """計算矩陣無窮範數 (max row sum)"""
        return max(sum(abs(self.data[r*self.cols + c]) for c in range(self.cols)) 
                   for r in range(self.rows))

    def swap_rows(self, r1, r2):
        if r1 == r2: return
        c = self.cols
        idx1, idx2 = r1 * c, r2 * c
        self.data[idx1:idx1+c], self.data[idx2:idx2+c] = \
            self.data[idx2:idx2+c], self.data[idx1:idx1+c]

    def multiply_vec(self, x):
        b = [self.dtype(0.0)] * self.rows
        for r in range(self.rows):
            s, row_off = self.dtype(0.0), r * self.cols
            for c in range(self.cols): s += self.data[row_off + c] * x[c]
            b[r] = s
        return b

class LUSolver:
    """
    EDA 工業級 LU 分解引擎
    具備：Scaled Partial Pivoting, Condition Tracking, Backward Error Monitoring
    """
    def __init__(self, options=None):
        self.options = options or SolverOptions()
        self.p_vector = []
        self.min_pivot, self.max_pivot = 0.0, 0.0
        self.A_norm = 0.0

    def factorize(self, matrix):
        """執行 A = LU 分解：實作 Scaled Partial Pivoting"""
        n, d, cols = matrix.rows, matrix.data, matrix.cols
        self.p_vector = list(range(n))
        self.min_pivot, self.max_pivot = float('inf'), 0.0
        self.A_norm = matrix.get_matrix_norm()
        
        # 預先計算每一列的範數，用於 Scaling [建議 1]
        row_norms = [matrix.get_row_norm(r) for r in range(n)]

        for i in range(n):
            # 1. 工業級主元選擇：Scaled Partial Pivoting
            max_scaled_val = -1.0
            pivot_row = i
            for r in range(i, n):
                val = abs(d[r * cols + i])
                # Scaled Value: abs(A[r,i]) / row_norm[r]
                scaled_val = val / (row_norms[r] + self.options.eps)
                if scaled_val > max_scaled_val + self.options.eps:
                    max_scaled_val, pivot_row = scaled_val, r

            actual_pivot_val = abs(d[pivot_row * cols + i])
            
            # 2. 深度診斷：Pivot Breakdown Check [建議 6]
            if not math.isfinite(actual_pivot_val) or \
               actual_pivot_val < max(self.options.pivot_abs_tol, 
                                      self.options.pivot_rel_tol * row_norms[pivot_row]):
                return SolverResult(status="SINGULAR", 
                                    error_msg="Pivot below tolerance (Possible floating node/loop)",
                                    row=i, pivot_val=actual_pivot_val)

            # 3. Swap Rows & Tracking
            if pivot_row != i:
                matrix.swap_rows(i, pivot_row)
                row_norms[i], row_norms[pivot_row] = row_norms[pivot_row], row_norms[i]
                self.p_vector[i], self.p_vector[pivot_row] = self.p_vector[pivot_row], self.p_vector[i]
            
            self.min_pivot = min(self.min_pivot, actual_pivot_val)
            self.max_pivot = max(self.max_pivot, actual_pivot_val)

            # 4. LU 核心運算
            pivot = d[i * cols + i]
            for j in range(i + 1, n):
                idx_ji = j * cols + i
                d[idx_ji] /= pivot
                factor = d[idx_ji]
                for k in range(i + 1, n):
                    d[j * cols + k] -= factor * d[i * cols + k]
        
        return "SUCCESS"

    def solve(self, matrix_lu, b_orig, matrix_orig=None):
        """具備 Backward Error 與 Stagnation Check 的求解核心"""
        n, d, cols = matrix_lu.rows, matrix_lu.data, matrix_lu.cols
        x = [b_orig[self.p_vector[i]] for i in range(n)]

        # LU 解算過程... (Forward/Backward Substitution)
        for i in range(n):
            off = i * cols
            for k in range(i): x[i] -= d[off + k] * x[k]
        for i in range(n - 1, -1, -1):
            off = i * cols
            for k in range(i + 1, n): x[i] -= d[off + k] * x[k]
            x[i] /= d[off + i]

        if not all(math.isfinite(abs(xi)) for xi in x):
            return SolverResult(status="NUMERIC_FAILURE", error_msg="Inf/NaN detected in solution")

        res_info = {"val": float('inf'), "back_err": 0.0, "count": 0}
        cond_hint = self.max_pivot / (self.min_pivot + self.options.eps)

        if matrix_orig:
            prev_res = float('inf')
            for i in range(self.options.refine_steps):
                ax = matrix_orig.multiply_vec(x)
                r_vec = [b_orig[j] - ax[j] for j in range(len(b_orig))]
                
                # 工業級 Scaling 殘差與 Backward Error [建議 3, 4]
                norm_r, norm_b, norm_x = max(abs(rv) for rv in r_vec), max(abs(bv) for bv in b_orig), max(abs(xv) for xv in x)
                current_res = norm_r / (self.A_norm * norm_x + norm_b + self.options.eps)
                backward_err = norm_r / (self.A_norm * norm_x + self.options.eps)

                # 迭代改進停滯檢查 [建議 5]
                if current_res > prev_res * self.options.stagnation_ratio: break
                
                res_info.update({"val": current_res, "back_err": backward_err, "count": i + 1})
                prev_res = current_res
                if current_res < self.options.zero_tol: break

                delta_x = self._solve_basic(matrix_lu, r_vec)
                x = [xv + dx for xv, dx in zip(x, delta_x)]

        return SolverResult(x=x, residual=res_info["val"], backward_error=res_info["back_err"],
                            status="SUCCESS", iterations=res_info["count"], cond_hint=cond_hint)

    def _solve_basic(self, matrix_lu, b_orig):
        """用於迭代改進的基礎求解，不進行額外的收斂檢查"""
        n, d, cols = matrix_lu.rows, matrix_lu.data, matrix_lu.cols
        # 注意：這裡假設 b_orig 已經是按照 p_vector 排好序的，或者需要重新排序？
        # 在 refine 過程中，r_vec 是基於原始矩陣算的，所以需要先根據 p_vector 換位
        x = [b_orig[self.p_vector[i]] for i in range(n)]

        # Forward Substitution
        for i in range(n):
            off = i * cols
            for k in range(i): x[i] -= d[off + k] * x[k]
        # Backward Substitution
        for i in range(n - 1, -1, -1):
            off = i * cols
            for k in range(i + 1, n): x[i] -= d[off + k] * x[k]
            x[i] /= d[off + i]
        
        return SolverResult(x=x)
