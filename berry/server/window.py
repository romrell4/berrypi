"""
Berry window class. Used for editing code
"""
import logging

from PyQt5 import QtCore, QtGui
from PyQt5.QtCore.Qt import ActionsContextMenu
from PyQt5.QtGui import QAction
from PyQt5.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CodeEditor(QTextEdit):
    """
    QTextEdit for editing code.
    """
    def __init__(self, parent=None):
        QTextEdit.__init__(self, parent)

        self.setContextMenuPolicy(ActionsContextMenu)

        flash_action = QAction("Flash", self)
        flash_action.triggered.connect(self.flash)
        self.addAction(flash_action)

    def set_server(self, server):
        self._server = server

    def flash(self):
        """
        Sends the flash message.
        """
        # TODO: get selected text and put in name

        payload = {
            'name': name,
        }

        # Flashes the client
        self._server.flash_client(payload)


class EditWindow(QWidget):
    """
    Window for editing code.
    """

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        font = QtGui.QFont('Monaco')
        font.setPointSize(21)

        self._name_textbox = QLineEdit()
        self._code_textbox = CodeEditor()

        self._name_textbox.setFont(font)
        self._code_textbox.setFont(font)

        self._save_button = QPushButton("Save Changes")
        self._save_button.clicked.connect(self.save_code_handler)

        # Container
        vbox = QVBoxLayout()

        vbox.addWidget(QLabel("Widget Name"))
        vbox.addWidget(self._name_textbox)

        vbox.addWidget(QLabel("Widget Handler Code"))
        vbox.addWidget(self._code_textbox)

        vbox.addWidget(self._save_button)

        self.setLayout(vbox)

        # Window settings
        self.resize(800, 800)
        self.setWindowTitle('Edit Code')

    def set_server(self, server):
        """
        Saves a reference to the server instance. Used in save_code_handler().
        """
        self._server = server

        # Set up Qt signals
        self._server._load_code_signal.connect(self.load_code)
        self._server._insert_name_signal.connect(self.insert_name)

    @QtCore.pyqtSlot(dict)
    def load_code(self, payload):
        """
        Loads the code into the QTextEdit instance.
        """
        self._guid = payload['guid']
        self._name_textbox.setText(payload['name'])
        self._code_textbox.setText(payload['code'])

        self.show()
        self._code_textbox.setFocus()
        self.raise_()

    @QtCore.pyqtSlot(str)
    def insert_name(self, name):
        """
        Inserts the berry name into the QTextEdit instance at the cursor.
        """
        cursor = self._code_textbox.textCursor()
        cursor.insertText(name)

        # Make sure the window is on top
        self.show()
        self.raise_()

    def save_code_handler(self):
        """
        Handler for when the Save Code button is clicked.
        """
        payload = {
            'guid': self._guid,
            'name': self._name_textbox.text(),
            'code': self._code_textbox.toPlainText(),
        }

        # Send code back to client
        self._server.send_edited_code(payload)

        # And hide the window
        self.hide()
