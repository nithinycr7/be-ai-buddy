"""SSML template for Azure AI Speech text-to-speech."""
from __future__ import annotations

SSML_TEMPLATE = """\
<speak version='1.0' xml:lang='en-IN' xmlns='http://www.w3.org/2001/10/synthesis'>
  <voice name='{voice}'>
    <prosody rate='0%' pitch='0%'>
      {text}
    </prosody>
  </voice>
</speak>"""
