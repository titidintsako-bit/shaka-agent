# Internationalization support for Shaka.
import json
import os
from typing import Dict, Optional

# Path to translation files
TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')

# Cache for translations
_translations: Dict[str, Dict[str, str]] = {}
_current_language = 'en'



def load_translations(language: str = 'en') -> None:
    """
    Load translations for the given language.
    Falls back to English if the file is not found.
    Includes protection against path traversal attacks.
    """
    global _translations, _current_language
    
    # Sanitize language input to prevent path traversal
    # Only allow alphanumeric characters, hyphens, and underscores
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', language):
        # Fall back to English for invalid language codes
        language = 'en'
    
    _current_language = language

    # Try to load the specified language
    lang_file = os.path.join(TRANSLATIONS_DIR, f"{language}.json")
    # Additional safety: ensure the normalized path is still within TRANSLATIONS_DIR
    lang_file = os.path.normpath(lang_file)
    if not lang_file.startswith(os.path.normpath(TRANSLATIONS_DIR)):
        # Path traversal attempt detected, fall back to English
        lang_file = os.path.join(TRANSLATIONS_DIR, "en.json")
    
    if os.path.exists(lang_file):
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                _translations[language] = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # If JSON is malformed or file can't be read, fall back to English
            en_file = os.path.join(TRANSLATIONS_DIR, "en.json")
            if os.path.exists(en_file):
                with open(en_file, 'r', encoding='utf-8') as f:
                    _translations[language] = json.load(f)
            else:
                _translations[language] = {}
    else:
        # Fallback to English
        en_file = os.path.join(TRANSLATIONS_DIR, "en.json")
        if os.path.exists(en_file):
            try:
                with open(en_file, 'r', encoding='utf-8') as f:
                    _translations[language] = json.load(f)
            except (json.JSONDecodeError, IOError):
                _translations[language] = {}
        else:
            # No translations at all
            _translations[language] = {}

def gettext(key: str) -> str:
    """
    Get the translated string for the given key.
    Returns the key itself if not found.
    Implements fallback to English.
    """
    lang_dict = _translations.get(_current_language, {})
    message = lang_dict.get(key)
    if message is None:
        # Fallback to English
        lang_dict = _translations.get('en', {})
        message = lang_dict.get(key)
    return message if message is not None else key


def ngettext(key: str) -> str:
    """
    Mark a string for translation (returns the key).
    """
    return key