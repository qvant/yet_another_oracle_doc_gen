import codecs


def add_header(file, text, size=1):
    tag = "h" + str(size)
    file.write('<{0}>{1}</{2}>'.format(tag, text, tag))


def add_link(file, anchor, text):
    file.write('<a href="#{0}">{1}</a>'.format(anchor, text))


def add_link_anchor(file, anchor):
    file.write('<a id="{0}"></a>'.format(anchor))


def add_new_line(file):
    file.write('<br>')


def add_table(file):
    file.write("<table border = 1>")


def add_table_row(file):
    file.write("<tr>")


def add_table_cell(file, text):
    file.write("<td>{}</td>".format(text))


def open_table_cell(file):
    file.write("<td>")


def close_table_cell(file):
    file.write("</td>")


def close_table(file):
    file.write("</table>")


def close_table_row(file):
    file.write("</tr>")


def open_list(file):
    file.write('<ul>')


def add_list_element(file, text):
    file.write('<li>{}</li>'.format(text))


def close_list(file):
    file.write('</ul>')


def write(file, text):
    file.write(text)


def init(file):
    file.write("<html>")
    file.write("<body>")


def open_file(filename):
    f = codecs.open(filename, 'w', "utf-8")
    return f


def close_file(file, file_name=None):
    file.write("</body>")
    file.write("</html>")
    file.close()
