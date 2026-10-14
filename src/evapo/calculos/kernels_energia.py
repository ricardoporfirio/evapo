"""Kernels OpenCL das fórmulas energéticas, sempre executados com FP64.

O backend fornece real_t, buffers por banda e a seleção/fallback do dispositivo.
As saídas permanecem float32, como no processamento NumPy.
"""

KERNELS_ENERGIA = r"""
#pragma OPENCL FP_CONTRACT OFF

__kernel void emissividades_sebal(__global const real_t *x,
                                 __global const real_t *p,
                                 __global float *y, const int n) {
    const int i = get_global_id(0);
    if (i >= n) return;
    const real_t ndvi = x[i], iaf = x[n+i];
    const uint qa = (uint)x[2*n+i];
    const int valido = ((qa & 31u) == 0u) && ((qa & 32u) == 0u);
    real_t estreita = (real_t)NAN, larga = (real_t)NAN;
    if (valido && ((qa & 128u) != 0u)) {
        estreita = (real_t)0.99;
        larga = (real_t)0.985;
    } else if (valido && isfinite(ndvi) && ndvi > (real_t)0 && ndvi <= (real_t)1
               && isfinite(iaf) && iaf >= (real_t)0) {
        estreita = iaf >= (real_t)3 ? (real_t)0.98 : (real_t)0.97 + (real_t)0.0033 * iaf;
        larga = iaf >= (real_t)3 ? (real_t)0.98 : (real_t)0.95 + (real_t)0.01 * iaf;
    }
    y[i] = (float)estreita;
    y[n+i] = (float)larga;
}

__kernel void termicos(__global const real_t *x, __global const real_t *p,
                       __global float *y, const int n) {
    const int i = get_global_id(0);
    if (i >= n) return;
    const real_t dn = x[i], estreita = x[n+i], larga = x[2*n+i];
    real_t radiancia = p[0] * dn + p[1];
    if (!(dn > (real_t)0 && isfinite(dn) && radiancia > (real_t)0))
        radiancia = (real_t)NAN;
    const real_t brilho = p[3] / log1p(p[2] / radiancia);
    const real_t eps_b10 = isfinite(estreita) && estreita > (real_t)0 && estreita <= (real_t)1
        ? estreita : (real_t)NAN;
    const real_t eps_larga = isfinite(larga) && larga > (real_t)0 && larga <= (real_t)1
        ? larga : (real_t)NAN;
    const real_t denominador = (real_t)1 + (p[4] * brilho / p[5]) * log(eps_b10);
    const real_t ts = denominador > (real_t)0 ? brilho / denominador : (real_t)NAN;
    y[i] = (float)radiancia;
    y[n+i] = (float)brilho;
    y[2*n+i] = (float)(ts - (real_t)273.15);
    y[3*n+i] = (float)(eps_larga * p[6] * pown(ts, 4));
}

__kernel void radiacoes(__global const real_t *x, __global const real_t *p,
                        __global float *y, const int n) {
    const int i = get_global_id(0);
    if (i >= n) return;
    const real_t entrada_tau = x[i];
    const real_t tau = isfinite(entrada_tau) && entrada_tau > (real_t)0 && entrada_tau < (real_t)1
        ? entrada_tau : (real_t)NAN;
    const real_t curta = p[0] * tau;
    real_t eps_ar = (real_t)0.85 * pow(-log(tau), (real_t)0.09);
    if (!(eps_ar <= (real_t)1)) eps_ar = (real_t)NAN;
    y[i] = (float)curta;
    y[n+i] = (float)eps_ar;
    if (p[2] == (real_t)0) return;
    const real_t longa = eps_ar * p[4] * pown(p[1], 4);
    y[2*n+i] = (float)longa;
    if (p[3] == (real_t)0) return;
    const real_t entrada_eps = x[n+i], entrada_ts = x[2*n+i], entrada_albedo = x[3*n+i];
    const real_t eps = isfinite(entrada_eps) && entrada_eps > (real_t)0 && entrada_eps <= (real_t)1
        ? entrada_eps : (real_t)NAN;
    const real_t ts = isfinite(entrada_ts) && entrada_ts > (real_t)-273.15
        ? entrada_ts : (real_t)NAN;
    const real_t albedo = isfinite(entrada_albedo) && entrada_albedo >= (real_t)0 && entrada_albedo <= (real_t)1
        ? entrada_albedo : (real_t)NAN;
    const real_t emitida = eps * p[4] * pown(ts + (real_t)273.15, 4);
    y[3*n+i] = (float)(((real_t)1 - albedo) * curta + longa - emitida - ((real_t)1 - eps) * longa);
}
"""
