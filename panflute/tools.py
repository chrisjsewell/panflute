# ---------------------------
# Imports
# ---------------------------

from .base import Element
from .elements import *
from .io import dump

import io
import os
import re
import sys
import json
import yaml
import shlex

# shutil.which: new in version 3.3
try:
    from shutil import which
except ImportError:
    from shutilwhich import which

from subprocess import Popen, PIPE
from functools import partial


# ---------------------------
# Constants
# ---------------------------

HorizontalSpaces = (Space, LineBreak, SoftBreak)

VerticalSpaces = (Para, )


# ---------------------------
# Functions
# ---------------------------

def stringify(element, newlines=True):
    """
    Return the raw text version of an elements (and its children element).

    Example:

        >>> from panflute import *
        >>> e1 = Emph(Str('Hello'), Space, Str('world!'))
        >>> e2 = Strong(Str('Bye!'))
        >>> para = Para(e1, Space, e2)
        >>> stringify(para)
        'Hello world! Bye!\n\n'

    :param newlines: add a new line after a paragraph (default True)
    :type newlines: :class:`bool`
    :rtype: :class:`str` 
    """

    def attach_str(e, doc, answer):
        if hasattr(e, 'text'):
            ans = e.text
        elif isinstance(e, HorizontalSpaces):
            ans = ' '
        elif isinstance(e, VerticalSpaces) and newlines:
            ans = '\n\n'
        elif type(e) == Citation:
            ans = ''
        else:
            ans = ''
        answer.append(ans)

    answer = []
    f = partial(attach_str, answer=answer)
    element.walk(f)
    return ''.join(answer)


def debug(*args, **kwargs):
    """
    Same as print, but prints to ``stderr``
    (which is not intercepted by Pandoc).
    """
    print(file=sys.stderr, *args, **kwargs)


def run_pandoc(text='', args=None):
    """
    Low level function that calls Pandoc with (optionally)
    some input text and/or arguments
    """

    if args is None:
        args = []

    pandoc_path = which('pandoc')
    if pandoc_path is None or not os.path.exists(pandoc_path):
        raise OSError("Path to pandoc executable does not exists")

    proc = Popen([pandoc_path] + args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate(input=text.encode('utf-8'))
    exitcode = proc.returncode
    if exitcode != 0:
        raise IOError(err)
    return out.decode('utf-8')


def convert_text(text,
                 input_format='markdown',
                 output_format='panflute',
                 standalone=False,
                 extra_args=None):
    """
    Convert formatted text (usually markdown) by calling Pandoc internally

    The default output format ('panflute') will return a tree
    of Pandoc elements. When combined with 'standalone=True', the tree root
    will be a 'Doc' element.

    Example:

        >>> from panflute import *
        >>> md = 'Some *markdown* **text** ~xyz~'
        >>> tex = r'Some $x^y$ or $x_n = \sqrt{a + b}$ \textit{a}'
        >>> convert_text(md)
        [Para(Str(Some) Space Emph(Str(markdown)) Space Strong(Str(text)) Space Subscript(Str(xyz)))]
        >>> convert_text(tex)
        [Para(Str(Some) Space Math(x^y; format='InlineMath') Space Str(or) Space Math(x_n = \sqrt{a + b}; format='InlineMath') Space RawInline(\textit{a}; format='tex'))]


    :param text: text that will be converted
    :type text: :class:`str` | :class:`.Element` | :class:`list` of :class:`.Element`
    :param input_format: format of the text (default 'markdown').
     Any Pandoc input format is valid, plus 'panflute' (a tree of Pandoc
     elements)
    :param output_format: format of the output
     (default is 'panflute' which creates the tree of Pandoc elements).
     Non-binary Pandoc formats are allowed (e.g. markdown, latex is allowed,
     but docx and pdf are not).
    :param standalone: whether the results will be a standalone document
     or not.
    :type standalone: :class:`bool`
    :param extra_args: extra arguments passed to Pandoc
    :type extra_args: :class:`list`
    :rtype: :class:`list` | :class:`.Doc` | :class:`str`

    Note: for a more general solution,
    see `pyandoc <https://github.com/kennethreitz/pyandoc/>`_
    by Kenneth Reitz.
    """

    if input_format == 'panflute':

        # Problem:
        #  We need a Doc element, but received a list of elements.
        #  So we wrap-up the list in a Doc, but with what pandoc-api version?
        #  (remember that Pandoc requires a matching api-version!)
        # Workaround: call Pandoc with empty text to get its api-version
        if not isinstance(text, Doc):
            tmp_doc = convert_text('', standalone=True)
            api_version = tmp_doc.api_version
            if isinstance(text, Element):
                text = [text]
            text = Doc(*text, api_version=api_version)

        # Dump the Doc into json
        with io.StringIO() as f:
            dump(text, f)
            text = f.getvalue()

    in_fmt = 'json' if input_format == 'panflute' else input_format
    out_fmt = 'json' if output_format == 'panflute' else output_format

    if extra_args is None:
        extra_args = []
    
    if standalone:
        extra_args.append('--standalone')

    out = inner_convert_text(text, in_fmt, out_fmt, extra_args)

    if output_format == 'panflute':
        out = json.loads(out, object_pairs_hook=from_json)

        if standalone:
            if not isinstance(out, Doc): # Pandoc 1.7.2 and earlier
                metadata, items = out
                out = Doc(*items, metadata=metadata)
        else:
            if isinstance(out, Doc): # Pandoc 1.8
                out = out.content.list
            else:
                out = out[1] # Pandoc 1.7.2 and earlier

    return out


def inner_convert_text(text, input_format, output_format, extra_args):
    # like convert_text(), but does not support 'panflute' input/output
    from_arg = '--from={}'.format(input_format)
    to_arg = '--to={}'.format(output_format)
    args = [from_arg, to_arg] + extra_args
    out = run_pandoc(text, args)
    out = "\n".join(out.splitlines())  # Replace \r\n with \n
    return out


def yaml_filter(element, doc, tag=None, function=None, tags=None,
                strict_yaml=False):
    '''
    Convenience function for parsing code blocks with YAML options

    This function is useful to create a filter that applies to
    code blocks that have specific classes.

    It is used as an argument of ``run_filter``, with two additional options:
    ``tag`` and ``function``.

    Using this is equivalent to having filter functions that:

    1. Check if the element is a code block
    2. Check if the element belongs to a specific class
    3. Split the YAML options (at the beginning of the block, by looking
       for ``...`` or ``---`` strings in a separate line
    4. Parse the YAML
    5. Use the YAML options and (optionally) the data that follows the YAML
       to return a new or modified element

    Instead, you just need to:

    1. Call ``run_filter`` with ``yaml_filter`` as the action function, and
       with the additional arguments ``tag`` and ``function``
    2. Construct a ``fenced_action`` function that takes four arguments:
       (options, data, element, doc). Note that options is a dict and data
       is a raw string. Notice that this is similar to the ``action``
       functions of standard filters, but with *options* and *data* as the
       new ones.

    Note: if you want to apply multiple functions to separate classes,
    you can use the ``tags`` argument, which receives a dict of
    ``tag: function`` pairs.

    Note: use the ``strict_yaml=True`` option in order to allow for more verbose
    but flexible YAML metadata: more than one YAML blocks are allowed, but
    they all must start with ``---`` (even at the beginning) and end with
    ``---`` or ``...``. Also, YAML is not the default content
    when no delimiters are set.

    Example::

        """
        Replace code blocks of class 'foo' with # horizontal rules
        """

        import panflute as pf

        def fenced_action(options, data, element, doc):
            count = options.get('count', 1)
            div = pf.Div(attributes={'count': str(count)})
            div.content.extend([pf.HorizontalRule] * count)
            return div

        if __name__ == '__main__':
            pf.run_filter(pf.yaml_filter, tag='foo', function=fenced_action)
    '''

    # Allow for either tag+function or a dict {tag: function}
    assert (tag is None) + (tags is None) == 1  # XOR
    if tags is None:
        tags = {tag: function}

    if type(element) == CodeBlock:
        for tag in tags:
            if tag in element.classes:
                function = tags[tag]

                if not strict_yaml:
                    # Split YAML and data parts (separated by ... or ---)
                    raw = re.split("^([.]{3,}|[-]{3,})$",
                                   element.text, 1, re.MULTILINE)
                    data = raw[2] if len(raw) > 2 else ''
                    data = data.lstrip('\n')
                    raw = raw[0]
                    try:
                        options = yaml.safe_load(raw)
                    except yaml.scanner.ScannerError:
                        debug("panflute: malformed YAML block")
                        return
                    if options is None:
                        options = {}

                else:
                    options = {}
                    data = []
                    raw = re.split("^([.]{3,}|[-]{3,})$",
                                   element.text, 0, re.MULTILINE)
                    rawmode = True
                    for chunk in raw:

                        chunk = chunk.strip('\n')
                        if not chunk:
                            continue

                        if rawmode:
                            if chunk.startswith('---'):
                                rawmode = False
                            else:
                                data.append(chunk)
                        else:
                            if chunk.startswith('---') or chunk.startswith('...'):
                                rawmode = True
                            else:
                                try:
                                    options.update(yaml.safe_load(chunk))
                                except yaml.scanner.ScannerError:
                                    debug("panflute: malformed YAML block")
                                    return

                    data = '\n'.join(data)

                return function(options=options, data=data,
                                element=element, doc=doc)


def shell(args, wait=True, msg=None):
    """
    Execute the external command and get its exitcode, stdout and stderr.
    """

    # Fix Windows error if passed a string
    if isinstance(args, str):
        args = shlex.split(args, posix=(os.name != "nt"))
        args = [arg.replace('/', '\\') for arg in args]

    if wait:
        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        out, err = proc.communicate(input=msg)
        exitcode = proc.returncode
        if exitcode != 0:
            raise IOError(err)
        return out
    else:
        DETACHED_PROCESS = 0x00000008
        proc = Popen(args, creationflags=DETACHED_PROCESS)

#def get_exe_path():
#    reg = winreg.ConnectRegistry(None,winreg.HKEY_CLASSES_ROOT)
#
#    # Fetch verb linked to the dta extension
#    path = '.dta'
#    key = winreg.OpenKey(reg, path)
#    verb = winreg.QueryValue(key, None) # Alternatives: .dta .do
#    
#    # Fetch command linked to that verb
#    path = '{}\shell\open\command'.format(verb)
#    key = winreg.OpenKey(reg, path)
#    cmd = winreg.QueryValue(key, None)
#    fn = cmd.strip('"').split('"')[0]
#    #raise(Exception(fn))
#    return fn
#
#def check_correct_executable(fn):
#    return os.path.isfile(fn) and 'stata' in fn.lower()


# ---------------------------
# Replacing content
# ---------------------------

def _replace_keyword(self, keyword, replacement, count=0):
    """
    replace_keyword(keyword, replacement[, count])

    Walk through the element and its children
    and look for Str() objects that contains
    exactly the keyword. Then, replace it.

    Usually applied to an entire document (a :class:`.Doc` element)

    Note: If the replacement is a block, it cannot be put in place of
    a Str element. As a solution, the closest ancestor (e.g. the parent)
    will be replaced instead, but only if possible
    (if the parent only has one child).

    Example:

    >>> from panflute import *
    >>> p1 = Para(Str('Spam'), Space, Emph(Str('and'), Space, Str('eggs')))
    >>> p2 = Para(Str('eggs'))
    >>> p3 = Plain(Emph(Str('eggs')))
    >>> doc = Doc(p1, p2, p3)
    >>> doc.content
    ListContainer(Para(Str(Spam) Space Emph(Str(and) Space Str(eggs))) Para(Str(eggs)) Plain(Emph(Str(eggs))))
    >>> doc.replace_keyword('eggs', Str('ham'))
    >>> doc.content
    ListContainer(Para(Str(Spam) Space Emph(Str(and) Space Str(ham))) Para(Str(ham)) Plain(Emph(Str(ham))))
    >>> doc.replace_keyword(keyword='ham', replacement=Para(Str('spam')))
    >>> doc.content
    ListContainer(Para(Str(Spam) Space Emph(Str(and) Space Str(ham))) Para(Str(spam)) Para(Str(spam)))

    :param keyword: string that will be searched (cannot have spaces!)
    :type keyword: :class:`str`
    :param replacement: element that will be placed in turn of the ``Str``
     element that contains the keyword.
    :type replacement: :class:`.Element`
    :param count: number of occurrences that will be replaced.
     If count is not given or is set to zero, all occurrences
     will be replaced.
    :type count: :class:`int`
    """

    def replace_with_inline(e, doc):
        if type(e) == Str and e.text == keyword:
            doc.num_matches += 1
            if not count or doc.num_matches <= count:
                return replacement

    def replace_with_block(e, doc):
        if hasattr(e, 'content') and len(e.content) == 1:
            ee = e.content[0]
            if type(ee) == Str and ee.text == keyword:
                if isinstance(e, Block):
                    doc.num_matches += 1
                    if not count or doc.num_matches <= count:
                        return replacement
                elif isinstance(e, Inline):
                    return Str(keyword)

    doc = self.doc
    if doc is None:
        raise Exception('No root document')
    doc.num_matches = 0
    if isinstance(replacement, Inline):
        return self.walk(replace_with_inline, doc)
    elif isinstance(replacement, Block):
        return self.walk(replace_with_block, doc)
    else:
        raise NotImplementedError(type(replacement))

# Bind the method
Element.replace_keyword = _replace_keyword
