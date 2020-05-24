import json
import codecs
from messages import M_TRUE, M_FALSE


class L18n:
    # Class for translation messages to chosen language
    def __init__(self):
        self.locale = ''
        self.encoding = None
        self.msg_map = []

    def set_encoding(self, encoding):
        self.encoding = encoding

    def set_locale(self, name):
        self.locale = name
        f = "l18n\\" + name + ".lng"
        fp = codecs.open(f, 'r', "utf-8")
        self.msg_map = json.load(fp)

    def get_message(self, msg_type):
        msg = self.msg_map[msg_type]
        if self.encoding is not None:
            msg = str(msg.encode(self.encoding))
        return msg

    def translate_bool(self, value):
        if value:
            msg = self.get_message(M_TRUE)
        else:
            msg = self.get_message(M_FALSE)
        return msg
