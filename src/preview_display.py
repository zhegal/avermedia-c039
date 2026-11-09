# SPDX-License-Identifier: GPL-2.0-or-later
"""Display-only sizing/deinterlace settings, never used by the archive encoder."""
def fit_4x3(width, height):
    width, height = max(1,int(width)), max(1,int(height))
    fitted_width = min(width, max(1,height*4//3))
    return fitted_width, min(height,max(1,fitted_width*3//4))


def rgb_filter(deinterlace, parity):
    if parity not in ('tff','bff'):
        raise ValueError('preview field order must be tff or bff')
    return f'bwdif=mode=send_field:parity={parity}:deint=all' if deinterlace else 'null'
