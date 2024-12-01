# app/color_design.py

# Predefined Tableau 10 inspired palette (16 colors)
TABLEAU10_PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
    '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
    '#bcbd22', '#17becf', '#aec7e8', '#ffbb78',
    '#98df8a', '#ff9896', '#c5b0d5', '#c49c94'
]

def design_color_palette():
    """
    Provide examples of color palettes for different roles and statuses.
    Returns a dictionary mapping roles and statuses to colors.
    """
    palette = {
        'roles': {
            'Anycast': '#1f77b4',        # Blue
            'Switch': '#ff7f0e',        # Orange
            'Router': '#2ca02c',        # Green
            'Firewall': '#d62728',      # Red
            'Workstation': '#9467bd',   # Purple
            'Other': '#808080'           # Gray
        },
        'statuses': {
            'Active': '#2ca02c',        # Green
            'Reserved': '#000000',      # Black (with 25% opacity)
            'Inactive': 'none'           # Transparent
        },
        'tags': {
            'Special': '#FF0000'        # Red
        },
        'background': '#ffffff',        # White
        'unallocated': 'none',           # Transparent
        'grid_lines': '#cccccc'         # Light Gray
    }
    return palette

def adjust_color_intensity(hex_color, factor):
    """
    Adjust the intensity of a hex color by a given factor.
    factor < 1: darker, factor > 1: lighter
    """
    if hex_color == 'none':
        return hex_color
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    adjusted = tuple(min(255, max(0, int(c * factor))) for c in rgb)
    return '#{:02x}{:02x}{:02x}'.format(*adjusted)

def blend_colors(color1, color2, alpha):
    """
    Blend two hex colors with a blending coefficient (alpha).
    
    Args:
        color1 (str): The first color in hex format (e.g., '#ff0000').
        color2 (str): The second color in hex format (e.g., '#0000ff').
        alpha (float): The blending coefficient (0.0 to 1.0).
                       0.0 returns color1, 1.0 returns color2.
    
    Returns:
        str: The resulting blended color in hex format.
    """
    if not color1 or color1 == 'none' or not color1.startswith('#'):
        return color1
    if not color2 or color2 == 'none' or not color2.startswith('#'):
        raise ValueError(f"Invalid color2: {color2}")
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"Alpha must be between 0.0 and 1.0. Given: {alpha}")
    
    color1 = color1.lstrip('#')
    color2 = color2.lstrip('#')
    rgb1 = tuple(int(color1[i:i+2], 16) for i in (0, 2, 4))
    rgb2 = tuple(int(color2[i:i+2], 16) for i in (0, 2, 4))
    
    blended = tuple(
        int((1 - alpha) * c1 + alpha * c2) for c1, c2 in zip(rgb1, rgb2)
    )
    return '#{:02x}{:02x}{:02x}'.format(*blended)
