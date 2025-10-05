# -*- coding: utf-8 -*-
"""
Utility functions for the folklore application.
Contains reusable helper functions for text processing, conversion, and formatting.
"""


def str_none(text):
    """
    Convert None to empty string.
    
    Args:
        text: Any value that might be None
        
    Returns:
        str: Empty string if text is None, otherwise the original text
    """
    if text is None:
        return ""
    return text


def roman_interpreter(roman):
    """
    Convert Roman numerals to Arabic numerals.
    
    Args:
        roman (str): Roman numeral string (e.g., 'IV', 'IX', 'XL')
        
    Returns:
        int: Arabic numeral equivalent
    """
    roman = roman.replace('Х', 'X')
    keys = [
        'IV', 'IX', 'XL', 'XC', 'CD', 'CM', 'I', 'V', 'X', 'L', 'C', 'D', 'M'
    ]
    to_arabic = {
        'IV': '4', 'IX': '9', 'XL': '40', 'XC': '90', 'CD': '400', 'CM': '900',
        'I': '1', 'V': '5', 'X': '10', 'L': '50', 'C': '100', 'D': '500',
        'M': '1000'}
    for key in keys:
        if key in roman:
            roman = roman.replace(key, ' {}'.format(to_arabic.get(key)))
    arabic = sum(int(num) for num in roman.split())
    return arabic


def mystem_interpreter(word, display, language='russian'):
    """
    Convert Mystem analysis results to a structured format.
    
    Args:
        word (dict): Mystem analysis result dictionary
        display (str): Display form of the word
        language (str): Language of analysis (default: 'russian')
        
    Returns:
        dict: Structured analysis result with word type, form, and grammatical analysis
    """
    from folklore_app.const import CATEGORIES
    
    result = []
    if 'analysis' in word:
        for i in word['analysis']:
            lex = i['lex']
            variants = i['gr'].split('=')
            variants[0] = variants[0].split(',')
            variants[1] = [
                x.split(',')
                for x in variants[1].strip('()').split('|')
            ]
            if variants[1] == [['']]:
                variants[1] = []
                cur = {'lex': lex}
                for var in variants[0]:
                    cur['gr.{}'.format(CATEGORIES[language][var])] = var
                result.append(cur)
                continue
            # TODO check this continue thing
            for j in variants[1]:
                cur = {'lex': lex}
                for var in variants[0] + j:
                    if var != '':
                        cur['gr.{}'.format(
                            CATEGORIES[language][var]
                        )] = var

                result.append(cur)
        return {
            'wtype': 'word',
            'wf': word['text'],
            'wf_display': display,
            'ana': result
        }
    return {
        'wtype': 'punkt',
        'wf': word['text'],
        'wf_display': display
    }


def convert_video_audio_new(text):
    """
    Convert video/audio entry text to a structured format before writing to database.
    
    Parses entries in the format:
    filename1;duration1
    filename2;duration2
    
    Args:
        text (str): Multi-line text with video/audio entries
        
    Returns:
        list: List of tuples (filename, duration) where duration is int
    """
    items = text.split('\n')
    result = []
    for i in items:
        one_item = i.split(';')
        if len(one_item) == 2:
            result.append((one_item[0], int(one_item[1])))
        else:
            result.append((one_item[0], 0))
    return result
