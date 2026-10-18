"""Narrow explicit abuse checks; not a general jailbreak-proof classifier."""
import re

def injected_instruction(text):
    patterns=[r'ignore\s+(?:all\s+)?(?:previous|prior|system|above)\s+(?:instructions|rules|messages)',
        r'(?:reveal|print|return|show|exfiltrate)\s+(?:the\s+|your\s+|all\s+)?(?:api[ _-]?keys?|system prompt|environment variables|session_secret)',
        r'\[/?INST\]|<\|(?:system|im_start|im_end)\|>|</?system>',
        r'you are now (?:DAN|an unrestricted|in developer mode)',r'override (?:the |your )?(?:system|safety)']
    return any(re.search(pattern,text,re.I) for pattern in patterns)

def unsafe_request(text):
    if injected_instruction(text):return 'I can help with AML research, but cannot follow instructions to override safeguards or reveal private configuration.'
    if re.search(r'(?:how (?:can|do|to)|help me|tell me).{0,100}(?:avoid (?:AML |transaction )?detection|evade (?:AML|SAR|CTR|reporting)|launder.{0,40}(?:undetected|without getting caught))',text,re.I):
        return 'I can explain AML controls and risk indicators, but cannot provide instructions for evading detection or reporting.'
    return None
