from imaplib import IMAP4_SSL
from re import compile

# A regexp for use with the helper function immediately below it
_list_response_pattern = compile(r'\((?P<flags>.*?)\) "(?P<delimiter>.*)" (?P<name>.*)')


def _parse_list_response(line):
    """A helper function for splitting up the response from the imap list method

    :param line: the string returned by a search in the imap library for each label
    :type line: str
    :return: a tuple containing flags on that box, the hierarchy delimiter, and the mailbox's name
    """
    flags, delimiter, mailbox_name = _list_response_pattern.match(line).groups()
    mailbox_name = mailbox_name.strip('"')
    return flags, delimiter, mailbox_name


class BadReturnStatus(Exception):
    pass


class ReadOnlyException(Exception):
    pass


def _ok(ok):
    """Many of the functions in the imap connection class return a tuple with a status and the result.
    This is a helper function to handle those.

    :param ok: Intended to be the first member of the tuples returned by the imap libraries functions
    :type ok: str
    :raise BadReturnStatus: Raised when ok's value does not indicate the request was processed
    """
    if ok != "OK":
        raise BadReturnStatus("status was {}".format(ok))


class Connection(object):

    def __init__(self, user=None, password=None, *args, **kwargs):
        """[MAGIC]
        Mostly a pass-through to the IMAP4_SSL object, this allows the login to be part of the initial connection.

        :param user: Imap username for login
        :type user: str or None
        :param password: Imap password for login
        :type password: str or None
        :param args: Pass-through to IMAP4_SSL
        :type args: list
        :param kwargs: Pass-through to IMAP4_SSL
        :type kwargs: dict
        """
        self.mailbox = 'INBOX'
        self.readonly = False

        # Composition, pass-through the arguments.
        # Unlike other parts of the library, this will throw an exception if it doesn't work (I think)
        self.parent = IMAP4_SSL(*args, **kwargs)

        # Handle the login if provided
        if user is not None and password is not None:
            self.login(user, password)

    def __getattr__(self, name):
        """[MAGIC]
        Using composition and a prefix instead of inheritance allows us to create replacements piece by piece,
        yet still allows use of non-replaced methods, without causing any comparability breaks in between.

        To pass-through to a child-method, prefix it with '_'.
        A side effect of this choice is that we can't name methods this way.

        :param name: Name of the attribute that is attempted to be got
        :type name: str
        :return: :raise AttributeError: To be compliant, raised when the mutated attribute isn't found
        """
        if name.startswith("_") and hasattr(self.parent, name[1:]):
            return getattr(self.parent, name[1:])
        else:
            raise AttributeError

    def login(self, user, password):
        """Authenticate the connection

        :param user: Imap username for login
        :type user: str
        :param password: Imap password for login
        :type password: str
        :return: A success message, includes username, and the users name
        """
        ok, value = self._login(user, password)
        _ok(ok)

        return value[0]

    def list(self, *args, **kwargs):
        boxes = {}
        ok, boxlist = self._list(*args, **kwargs)
        _ok(ok)

        for box_line in boxlist:
            flags, delimiter, name = _parse_list_response(box_line)
            this_box = {
                'flags': flags,
                'delimiter': delimiter
            }
            boxes[name] = this_box

        return boxes

    def select(self, mailbox="INBOX", readonly=False):
        self.switch(mailbox, readonly)

        return MailBox(self, mailbox, readonly)

    def switch(self, mailbox="INBOX", readonly=False):
        ok, messages = self._select(mailbox, readonly)
        _ok(ok)
        self.mailbox = mailbox
        self.readonly = self.readonly

    def search(self, *args, **kwargs):
        charset = kwargs.pop("charset", None)
        ok, results = self._search(charset, *args, **kwargs)
        _ok(ok)
        if results[0] == '':
            return []
        else:
            ids = results[0].split(' ')
            return ids

    def fetch(self, nums, *args, **kwargs):
        num_string = ' '.join(str(n) for n in nums)
        command = "(" + " ".join(args) + ")"
        ok, result = self._fetch(num_string, command, **kwargs)
        _ok(ok)
        return result

    def store(self, messages, flags, command="+", silent=False):
        command += "FLAGS"
        if silent:
            command += ".SILENT"
        new_flag_list = []
        for message in messages:
            ok, new_flags = self._store(message, command, flags)
            _ok(ok)
            new_flag_list.append(new_flags)
        return new_flag_list


class MailBox(object):

    def __init__(self, connection, mailbox, readonly):
        self.connection = connection
        self._mailbox, self._readonly = mailbox, readonly

    def _select(self):
        if self.connection.mailbox != self._mailbox:
            self.connection.switch(self._mailbox, self._readonly)

    def search(self, *args, **kwargs):
        self._select()
        messages = []
        for message in self.connection.search(*args, **kwargs):
            messages.append(Message(self, message))
        return messages

    def fetch(self, nums, *args):
        self._select()
        return self.connection.fetch(nums, *args)

    def store(self, *args, **kwargs):
        if self._readonly:
            raise ReadOnlyException
        self._select()
        return self.connection.store(*args, **kwargs)


class Message(MailBox):

    def __init__(self, inherit, num):
        super(Message, self).__init__(inherit.connection, inherit._mailbox, inherit._readonly)
        self.num = num

    def fetch(self, *args):
        return super(Message, self).fetch(str(self.num), *args)

    def store(self, flags, command="+", silent=False):
        new_flags = super(Message, self).store([self.num], flags, command=command, silent=silent)
        return new_flags[0]
