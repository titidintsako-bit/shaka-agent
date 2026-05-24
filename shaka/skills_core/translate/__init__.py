"""Translate Skill for Shaka.

Provides basic English to Zulu translation using a local dictionary.
"""

import json
import os
from shaka.i18n import gettext as _

# Path to the custom translation dictionary (user-extendable)
USER_TRANSLATIONS_PATH = os.path.expanduser("~/.shaka/translations.json")

# Built-in dictionary of common English to Zulu translations
# Seeded with some common words and phrases from the i18n system and more
BUILT_IN_TRANSLATIONS = {
    # Greetings and basics
    "hello": "sawubona",
    "hi": "sawubona",
    "yes": "yebo",
    "no": "cha",
    "please": "ngiyacela",
    "thank you": "ngiyabonga",
    "thanks": "ngiyabonga",
    "excuse me": "ngiyacela",
    "sorry": "ngiyaxolisa",
    "goodbye": "hamba kahle",
    "see you later": "ngiyanakubona ndawonye",
    "good morning": "kusihlale",
    "good afternoon": "kusihlale",
    "good evening": "kusihlale",
    "good night": "usaluko",
    "how are you?": "unjani?",
    "i am fine": "ngiyaphila",
    "and you?": "nawe?",
    "what is your name?": "ubani igama lakho?",
    "my name is": "igama lamingu",
    "nice to meet you": "kuyahlangana kunomuthando",
    "please speak slowly": "ngiyacela uyekezela noma uphantse",
    "i don't understand": "angaqondi",
    "can you repeat that?": "ungase benyusa?",
    "where is the bathroom?": "ini indawo yokuhlambela?",
    "water": "amanzi",
    "food": "ukudla",
    "house": "indlu",
    "car": "imoto",
    "bus": "ibusisi",
    "train": "utreni",
    "airport": "isithumuli sendlulamithi",
    "hospital": "isezifo",
    "police": "amapolisa",
    "help": "usizo",
    "emergency": "inkqiqo",
    # Numbers
    "one": "kunye",
    "two": "kubili",
    "three": "kuthathu",
    "four": "kune",
    "five": "kuthlanu",
    "six": "isithupha",
    "seven": "isikhombisa",
    "eight": "isishiyagalombili",
    "nine": "isishiyagalolunye",
    "ten": "ishumi",
    # Common verbs
    "to be": "ukuba",
    "to have": "ukuba na",
    "to go": "ukuhamba",
    "to come": "ukuzoba",
    "to eat": "ukudla",
    "to drink": "ukunwa",
    "to sleep": "ukulala",
    "to work": "ukusebenza",
    "to learn": "ukufunda",
    "to teach": "ukufundisa",
    # From the i18n system (interface words)
    "error": "ngumekho",
    "warning": "isibonakaliso",
    "ok": "vumela",
    "config": "umhlelo",
    "skills": "amakhono",
    "memory": "amaphiko",
    "data": "imibhalo",
    "system": "isistimi",
    "check": "uphando",
    "complete": "phazamise",
    # Actions
    "run": "githela",
    "start": "qala",
    "stop": "phinda",
    "list": "faka",
    "view": "buka",
    "clear": "suka",
    "edit": "shangisa",
    "create": "qala",
    "delete": "suka",
    # Tech terms
    "api": "umuthi we-API",
    "key": "umuthi",
    "file": "ifayili",
    "directory": "isigeja",
    "folder": "isigeja",
    "command": "umgangatho",
    "terminal": "iterminal",
    "python": "uthayithon",
}

class SkillHandler:
    def __init__(self):
        """Initialize the translation skill."""
        self.translations = dict(BUILT_IN_TRANSLATIONS)  # Start with built-in
        self.load_user_translations()
    
    def load_user_translations(self):
        """Load user-extended translations from file."""
        if os.path.exists(USER_TRANSLATIONS_PATH):
            try:
                with open(USER_TRANSLATIONS_PATH, 'r', encoding='utf-8') as f:
                    user_trans = json.load(f)
                    self.translations.update(user_trans)
            except Exception as e:
                # If we can't load, continue with built-in only
                pass
    
    def save_user_translations(self):
        """Save user-extended translations to file."""
        # Only save the user-added ones (not the built-in)
        user_only = {k: v for k, v in self.translations.items() 
                     if k not in BUILT_IN_TRANSLATIONS}
        if user_only:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(USER_TRANSLATIONS_PATH), exist_ok=True)
            with open(USER_TRANSLATIONS_PATH, 'w', encoding='utf-8') as f:
                json.dump(user_only, f, indent=2, ensure_ascii=False)
    
    def get_tool_def(self):
        """Return the tool definition for LLM consumption."""
        return {
            "type": "function",
            "function": {
                "name": "translate",
                "description": "Translate English text to Zulu using a local dictionary",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The English text to translate to Zulu"
                        },
                        "add_translation": {
                            "type": "object",
                            "description": "Optional: Add a new translation to the dictionary",
                            "properties": {
                                "english": {
                                    "type": "string",
                                    "description": "The English word or phrase"
                                },
                                "zulu": {
                                    "type": "string",
                                    "description": "The Zulu translation"
                                }
                            },
                            "required": ["english", "zulu"]
                        }
                    },
                    "required": ["text"]
                }
            }
        }
    
    def run(self, message: str, context: dict) -> str:
        """Main entry point for the translate skill."""
        # Extract parameters from context
        kwargs = context.get("kwargs", {})
        text = kwargs.get("text", "").strip()
        add_translation = kwargs.get("add_translation")
        
        if not text and not add_translation:
            return _("Please provide text to translate or specify a new translation to add.")
        
        # Handle adding a new translation
        if add_translation:
            english = add_translation.get("english", "").strip().lower()
            zulu = add_translation.get("zulu", "").strip()
            if not english or not zulu:
                return _("Both English and Zulu text are required to add a translation.")
            
            # Add to our translations dictionary
            self.translations[english] = zulu
            # Save to user file
            self.save_user_translations()
            return _("Added translation: '{}' -> '{}'").format(english, zulu)
        
        # Translate the text
        # Simple approach: translate word by word (for now)
        # For better phrase translation, we would need to check multi-word phrases first
        words = text.lower().split()
        translated_words = []
        
        for word in words:
            # Remove punctuation for lookup, but keep track to add back
            import string
            clean_word = word.strip(string.punctuation)
            if clean_word in self.translations:
                translated_words.append(self.translations[clean_word])
            else:
                # If not found, keep the original word (with possible punctuation)
                translated_words.append(word)
        
        # Join back together
        translated_text = " ".join(translated_words)
        
        # If we want to try phrase matching, we could do that here, but for simplicity,
        # we'll just do word-by-word and note limitations.
        if translated_text.lower() == text.lower():
            # No translations were found
            return _("Could not translate '{}'. No matching words found in dictionary. Consider adding a translation.").format(text)
        else:
            return _("Translation: {}").format(translated_text)