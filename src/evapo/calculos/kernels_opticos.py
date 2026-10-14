"""Kernels OpenCL para reflectância e índices; fórmulas de referência em NumPy."""

KERNELS_OPTICOS = r"""
#pragma OPENCL FP_CONTRACT OFF

__kernel void reflectancias(__global const real_t *x, __global const real_t *p,
                           __global float *y, const int n) {
    int i = get_global_id(0);
    uint qa = (uint)x[7*n+i], sat = (uint)x[8*n+i];
    int area = x[9*n+i] != 0 && (qa & 31) == 0 && (sat & 2048) == 0;
    for (int b=0; b<7; ++b) {
        real_t dn = x[b*n+i];
        real_t rho = (dn*p[1+2*b] + p[2+2*b]) / p[0];
        y[b*n+i] = area && dn != 0 && (sat & (1u<<b)) == 0 ? (float)rho : NAN;
    }
}

inline float savi_pixel(float red, float nir, float l) {
    float den = (nir + red) + l;
    if (!isfinite(red) || !isfinite(nir) || red < 0 || nir < 0 || den <= 1.0e-8f)
        return NAN;
    float s = ((1.0f+l)*(nir-red)) / den;
    return s >= -1.0f && s <= 1.0f ? s : NAN;
}

__kernel void opticos(__global const real_t *x, __global const real_t *p,
                     __global float *y, const int n) {
    int i = get_global_id(0);
    float albedo = 0;
    int valido = 1;
    for (int b=0; b<6; ++b) {
        float rho = (float)x[b*n+i];
        valido = valido && isfinite(rho) && rho >= 0;
        albedo = albedo + (float)p[2+b]*rho;
    }
    y[i] = valido ? clamp(albedo, 0.0f, 1.0f) : NAN;
    float red = (float)x[2*n+i], nir = (float)x[3*n+i];
    float den = nir + red;
    y[n+i] = isfinite(red) && isfinite(nir) && red >= 0 && nir >= 0 && den > 1.0e-8f
        ? (nir-red)/den : NAN;
    y[2*n+i] = savi_pixel(red, nir, (float)p[0]);
    float s = savi_pixel(red, nir, (float)p[1]);
    float iaf = NAN;
    if (isfinite(s)) {
        if (s <= 0.1f) iaf = 0;
        else if (s >= 0.687f) iaf = 6;
        else iaf = clamp(-log((0.69f-s)/0.59f)/0.91f, 0.0f, 6.0f);
    }
    y[3*n+i] = iaf;
}
"""
