"""Zulu-inspired ASCII art and visual elements for Shaka.

All art is terminal-safe and uses box-drawing + Unicode characters.
Inspired by traditional Zulu beadwork patterns, shield motifs, and the isigebengu symbol.
"""

SHAKA_LOGO = r"""
  ╔════════════════════════════════════════════════════════════╗
  ║  ███████╗██╗  ██╗ █████╗ ███╗   ███╗██████╗ ██╗   ██╗     ║
  ║  ██╔════╝██║  ██║██╔══██╗████╗ ████║██╔══██╗██║   ██║     ║
  ║  ███████╗███████║███████║██╔████╔██║██████╔╝██║   ██║     ║
  ║  ╚════██║██╔══██║██╔══██║██║╚██╔╝██║██╔══██╗██║   ██║     ║
  ║  ███████║██║  ██║██║  ██║██║ ╚═╝ ██║██████╔╝╚██████╔╝     ║
  ║  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝  ╚═════╝      ║
  ║                                                            ║
  ║         ═══  Personal AI Assistant  ═══                    ║
  ╚════════════════════════════════════════════════════════════╝
"""

SHAKA_LOGO_SMALL = """
    .d8888b.  888    888
   d88P  Y88b 888    888
   Y88b.      888    888
    "Y888b.   8888888888
       "Y88b. 888    888
         "888 888    888
   Y88b  d88P 888    888
    "Y8888P"  888    888
"""

# Zulu-inspired decorative borders using traditional patterns
ZULU_BORDER_TOP = """
  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆      ┃"""

ZULU_BORDER_BOTTOM = """  ┃  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ◆  ◇  ┃
  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"""

# Traditional Zulu beadwork pattern
BEAD_PATTERN = "◆ ◇ ◆ ◇ ◆ ◇ ◆ ◇ ◆ ◇ ◆ ◇ ◆ ◇ ◆ ◇ ◆"
BEAD_PATTERN_SHORT = "◆ ◇ ◆ ◇ ◆"

# Shield-inspired dividers
SHIELD_DIVIDER = """  ╔══════════════════════════════════════════════════════════╗"""
SHIELD_DIVIDER_BOTTOM = """  ╚══════════════════════════════════════════════════════════╝"""

# Spear pattern
SPEAR_PATTERN = "⚔⚔⚔ ⚔⚔⚔ ⚔⚔⚔ ⚔⚔⚔"

# Welcome splash screen for TUI
WELCOME_SPLASH = """
"""

def get_welcome_splash():
    """Full welcome screen with Zulu aesthetic."""
    lines = []
    lines.append(ZULU_BORDER_TOP)
    lines.append("  ┃                                                         ┃")
    lines.append("  ┃               S H A K A                           ┃")
    lines.append("  ┃          South African AI Developer Agent              ┃")
    lines.append(BEAD_PATTERN_SHORT.center(63, " "))
    lines.append("  ┃                                                         ┃")
    lines.append("  ┃       Built in South Africa, for the world.            ┃")
    lines.append("  ┃                                                         ┃")
    lines.append(ZULU_BORDER_BOTTOM)
    return "\n".join(lines)

def get_small_header():
    """Compact header for the status bar."""
    return f" {BEAD_PATTERN_SHORT} ⚡ SHAKA {BEAD_PATTERN_SHORT} "

def get_section_divider(title=""):
    """Zulu-style section divider."""
    if title:
        return f"  {SPEAR_PATTERN}  {title}  {SPEAR_PATTERN}  "
    return f"  {SPEAR_PATTERN}  "

def get_memory_header(count):
    return f"""
  ┌─────────────────────────────────────────────────────────────┐
  │  ◆ MEMORY ◆ {count} memories stored {'│':>15}"""
