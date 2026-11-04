# app/color_design.py

# Tenant fills: a Tableau 10 inspired palette of 16 colors, by tenant id
TABLEAU10_PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
    '#9467bd', '#8c564b', '#e377c2', '#e5c100',  # yellow, not gray: gray reads as a reserved IP
    '#bcbd22', '#17becf', '#aec7e8', '#ffbb78',
    '#98df8a', '#ff9896', '#c5b0d5', '#c49c94'
]

BACKGROUND_COLOR = '#ffffff'
GRID_LINE_COLOR = '#cccccc'


def blend_colors(color1, color2, alpha):
    """
    Blend two hex colors: alpha 0.0 returns color1, 1.0 returns color2.
    A color1 that is not a hex color ('none', None) is returned as is.
    """
    if not color1 or color1 == 'none' or not color1.startswith('#'):
        return color1
    if not color2 or color2 == 'none' or not color2.startswith('#'):
        raise ValueError(f"Invalid color2: {color2}")
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"Alpha must be between 0.0 and 1.0. Given: {alpha}")
    rgb1 = tuple(int(color1[i:i + 2], 16) for i in (1, 3, 5))
    rgb2 = tuple(int(color2[i:i + 2], 16) for i in (1, 3, 5))
    blended = tuple(int((1 - alpha) * c1 + alpha * c2) for c1, c2 in zip(rgb1, rgb2))
    return '#{:02x}{:02x}{:02x}'.format(*blended)
