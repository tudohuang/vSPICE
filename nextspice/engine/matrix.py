import math
from abc import ABC, abstractmethod

class MatrixBase(ABC):
    @abstractmethod
    def add_at(self, r, c, val): pass
    @abstractmethod
    def get_row_norm(self, r): pass
    @abstractmethod
    def multiply_vec(self, x): pass
    @abstractmethod
    def get_max_abs(self): pass
    @abstractmethod
    def swap_rows(self, r1, r2): pass
    @abstractmethod
    def copy(self): pass

class DenseMatrix(MatrixBase):
    """工業級稠密矩陣：支援嚴格數值檢查與 Debug 模式"""
    def __init__(self, rows, cols, is_complex=False, strict_numeric=False):
        self.rows, self.cols = rows, cols
        self.is_complex = is_complex
        self.strict_numeric = strict_numeric # 建議修 3: 開發期抓兇手
        self.dtype = complex if is_complex else float
        self.data = [self.dtype(0.0)] * (rows * cols)

    def add_at(self, r, c, val):
        if r < 0 or c < 0: return # 地線忽略
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            raise IndexError(f"Matrix Index ({r},{c}) Out of Range")
            
        if not math.isfinite(abs(val)):
            if self.strict_numeric: # 建議修 3
                raise ValueError(f"Numerical Error: Detected {val} at ({r},{c}) during stamping")
            return 
        self.data[r * self.cols + c] += val

    def get_row_norm(self, r):
        off = r * self.cols
        return max((abs(self.data[off + c]) for c in range(self.cols)), default=0.0)

    def get_max_abs(self):
        return max((abs(x) for x in self.data), default=0.0)

    def swap_rows(self, r1, r2):
        if r1 == r2: return
        i1, i2 = r1 * self.cols, r2 * self.cols
        self.data[i1:i1+self.cols], self.data[i2:i2+self.cols] = \
            self.data[i2:i2+self.cols], self.data[i1:i1+self.cols]

    def multiply_vec(self, x):
        b = [self.dtype(0.0)] * self.rows
        for r in range(self.rows):
            s, off = self.dtype(0.0), r * self.cols
            for c in range(self.cols):
                s += self.data[off + c] * x[c]
            b[r] = s
        return b

    def copy(self):
        new_mat = DenseMatrix(self.rows, self.cols, self.is_complex, self.strict_numeric)
        new_mat.data = self.data[:]
        return new_mat