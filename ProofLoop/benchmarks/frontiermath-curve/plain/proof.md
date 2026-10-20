The answer is **\(\boxed{3,814,708,984,376}\)**.

Nonzero triples up to scaling are points on the projective curve
\[
C:\quad x^3y+y^3z+z^3x=0
\]
over \(\mathbb F_{5^{18}}\).

The curve is smooth. If any coordinate is zero, its partial derivatives force all three coordinates to be zero, which is impossible in projective space. If \(xyz\ne0\), set \(A=x^3y\), \(B=y^3z\), and \(D=z^3x\). Multiplying the three partial derivatives by \(x,y,z\), respectively, gives
\[
3A+D=A+3B=B+3D=0.
\]
The coefficient matrix has determinant \(28\equiv3\pmod5\), so \(A=B=D=0\), another contradiction. Thus \(C\) is a smooth plane quartic of genus \((4-1)(4-2)/2=3\).

Let \(N_n=\#C(\mathbb F_{5^n})\). Direct exact counts give
\[
\begin{array}{c|ccc}
n&1&2&3\\ \hline
N_n&6&26&126
\end{array}
\]
Here is reproducible Python for those counts. It represents each field as \(\mathbb F_5[t]/(p)\); the listed polynomials are irreducible.
```python
from itertools import product

def mul(a, b, p):
    n = len(p)
    c = [0] * (2*n - 1)
    for i in range(n):
        for j in range(n):
            c[i+j] += a[i] * b[j]
    for k in range(2*n - 2, n - 1, -1):
        v = c[k] % 5
        for j in range(n):
            c[k-n+j] -= v * p[j]
    return tuple(v % 5 for v in c[:n])

def add(a, b):
    return tuple((u+v) % 5 for u, v in zip(a, b))

for p in [(0,), (2, 0), (1, 1, 0)]:  # t, t²+2, t³+t+1
    n = len(p)
    elements = list(product(range(5), repeat=n))
    cubes = {u: mul(mul(u, u, p), u, p) for u in elements}
    zero = (0,) * n
    affine = sum(
        add(add(y, mul(cubes[y], z, p)), cubes[z]) == zero
        for y in elements for z in elements
    )
    print(n, affine + 2)
```
The \(+2\) accounts for the two points with \(x=0\). With \(x=1\), the equation counted by the loop is \(y+y^3z+z^3=0\).

Write \(N_n=5^n+1-\sum_{i=1}^6\alpha_i^n\). The three counts show that the first three power sums of the \(\alpha_i\) vanish. Newton’s identities and the genus-three zeta functional equation then give
\[
\prod_{i=1}^6(1-\alpha_iT)=1+125T^6.
\]
Consequently every \(\alpha_i^6=-125\), and
\[
N_{18}=5^{18}+1-\sum_{i=1}^6\alpha_i^{18}
=5^{18}+1+6\cdot125^3
=\boxed{3,814,708,984,376}.
\]
There is no unresolved gap.