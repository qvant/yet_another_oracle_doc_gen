import yet_another_oracle_doc_gen.report_functions.html as html
#import yet_another_oracle_doc_gen.report_functions.ms_word as word
MODE_HTML = "HTML"
MODE_WORD = "DOCX"


class Report:
    def __init__(self, mode=MODE_HTML):
        self.file = None
        self.file_name = None
        self.mode = mode
        if self.mode == MODE_HTML:
            self._add_header = html.add_header
            self._write = html.write
            self._set_file = html.open_file
            self._close_file = html.close_file
            self._init = html.init
            self._new_line = html.add_new_line
            self._add_link = html.add_link
            self._add_link_anchor = html.add_link_anchor
            self._add_table = html.add_table
            self._add_table_row = html.add_table_row
            self._add_table_cell = html.add_table_cell
            self._close_table = html.close_table
            self._close_table_row = html.close_table_row
            self._open_table_cell = html.open_table_cell
            self._close_table_cell = html.close_table_cell
            self._add_list_element = html.add_list_element
            self._open_list = html.open_list
            self._close_list = html.close_list
        # elif self.mode == MODE_WORD:
        #     self._add_header = word.add_header
        #     self._write = word.write
        #     self._set_file = word.open_file
        #     self._close_file = word.close_file
        #     self._init = word.init
        #     self._new_line = word.add_new_line
        #     self._add_link = word.add_link
        #     self._add_link_anchor = word.add_link_anchor
        #     self._add_table = word.add_table
        #     self._add_table_row = word.add_table_row
        #     self._add_table_cell = word.add_table_cell
        #     self._close_table = word.close_table
        #     self._close_table_row = word.close_table_row
        #     self._open_table_cell = word.open_table_cell
        #     self._close_table_cell = word.close_table_cell
        #     self._add_list_element = word.add_list_element
        #     self._open_list = word.open_list
        #     self._close_list = word.close_list
        else:
            raise ValueError('Unsupported report type: {}'.format(mode))

    def set_file(self, filename):
        self.file = self._set_file(filename)
        self.file_name = filename

    def add_header(self, text, size=1):
        self._add_header(self.file, text, size)

    def write(self, text):
        self._write(self.file, text)

    def close(self):
        self._close_file(self.file, self.file_name)

    def init(self):
        self._init(self.file)

    def new_line(self):
        self._new_line(self.file)

    def add_link(self, anchor, text):
        self._add_link(self.file, anchor, text)

    def add_link_anchor(self, anchor):
        self._add_link_anchor(self.file, anchor)

    def add_table(self):
        self._add_table(self.file)

    def open_table_row(self):
        self._add_table_row(self.file)

    def close_table_row(self):
        self._close_table_row(self.file)

    def add_table_row(self, cells):
        self._add_table_row(self.file)
        self.add_table_cells(cells)
        self._close_table_row(self.file)

    def add_table_cell(self, text):
        self._add_table_cell(self.file, text)

    def add_table_cells(self, text_array):
        for i in text_array:
            self._add_table_cell(self.file, i)

    def open_table_cell(self):
        self._open_table_cell(self.file)

    def close_table_cell(self):
        self._close_table_cell(self.file)

    def close_table(self):
        self._close_table(self.file)

    def add_list(self, arr):
        self._open_list(self.file)
        for i in arr:
            self._add_list_element(self.file, i)
        self._close_list(self.file)
