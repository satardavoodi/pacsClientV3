"""Shared AI usage presentation; all history/network I/O runs off the Qt thread."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QComboBox
from modules.ai_imaging.eagle_eye_remote.administration import usage_snapshot
from modules.ai_imaging.eagle_eye_remote.usage import group_labels

class AIUsageWidget(QGroupBox):
    def __init__(self, category, parent=None, *, loader=None):
        super().__init__('Server processing usage', parent)
        self.category = category
        self._loader = loader or usage_snapshot
        self._future = None
        self._loaded = False
        self._snapshot = None
        self._server_view = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='AIUsageSettings')
        pool = self._pool
        self.destroyed.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
        layout = QVBoxLayout(self)
        self.description = QLabel('Usage by module / function from retained server records. Token counts are provider-reported, not estimates or billing balances.')
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.client_filter = QComboBox(self)
        self.client_filter.setToolTip('Filter by the authenticated sender retained in server history. Legacy device records remain separate from user identities.')
        self.client_filter.hide()
        self.client_filter.currentIndexChanged.connect(self._filter_changed)
        layout.addWidget(self.client_filter)
        self._fields = [('Requests','requests'), ('Completed','completed'),
                        ('Failed','failed'), ('Pending','pending'),
                        ('Input tokens','input_tokens'), ('Output tokens','output_tokens'),
                        ('Total tokens','total_tokens'), ('Missing token records','requests_without_complete_token_usage')]
        self.table = QTableWidget(0, len(self._fields) + 1)
        self.table.setHorizontalHeaderLabels(['Module / function'] + [label for label,_ in self._fields])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(300)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeaderItem(1).setToolTip('Requests accepted by the server for this module / function.')
        self.table.horizontalHeaderItem(3).setToolTip('Failed, cancelled or interrupted on the server.')
        self.table.horizontalHeaderItem(8).setToolTip('Requests without both reported input and output token counts.')
        self._placeholder('Not loaded')
        layout.addWidget(self.table)
        self.status = QLabel('Refresh to read usage through the shared Eagle Eye connection.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh_button = QPushButton('Refresh usage')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    def _placeholder(self, text):
        labels=list(group_labels(self.category).values())
        offset=int(self._server_view)
        self.table.setColumnCount(len(self._fields)+1+offset)
        self.table.setHorizontalHeaderLabels((['Authenticated client'] if offset else [])+
                                            ['Module / function']+[label for label,_ in self._fields])
        self.table.setRowCount(len(labels))
        for row,label in enumerate(labels):
            if offset:
                self.table.setItem(row,0,QTableWidgetItem('Not available'))
            self.table.setItem(row,offset,QTableWidgetItem(label))
            for column in range(offset+1,self.table.columnCount()):
                self.table.setItem(row,column,QTableWidgetItem(text))

    def _filter_changed(self, _index):
        if self._snapshot is None:
            return
        try:
            self._render(self._snapshot[self.category])
        except Exception:
            self._placeholder('Unavailable')

    def _render_user_audit(self, snapshot):
        from modules.ai_imaging.eagle_eye_remote.user_usage import validate_user_usage
        validate_user_usage(snapshot)
        prefix = {'eagle_eye': 'imaging', 'echomind': 'echomind', 'agent': 'secretary'}[self.category]
        rows = [row for row in snapshot['counts'] if row['operation'] == prefix or row['operation'].startswith(prefix + '.')]
        self._server_view = False
        self._snapshot = None
        self.client_filter.hide()
        self.description.setText('Your authenticated Eagle Eye access audit. These are request outcomes; provider token totals are not reported by this protocol.')
        self.table.clearContents()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['Operation', 'Outcome', 'Requests'])
        self.table.setRowCount(max(1, len(rows)))
        for index, row in enumerate(rows):
            for column, value in enumerate((row['operation'], row['outcome'], str(row['requests']))):
                self.table.setItem(index, column, QTableWidgetItem(value))
        if not rows:
            self.table.setItem(0, 0, QTableWidgetItem('No recorded operations'))
        self.status.setText('This signed-in user only. Retained access audit; token accounting is unavailable.')

    def _render(self, value):
        groups=value.get('groups')
        if not isinstance(groups,list) or not 1 <= len(groups) <= 64:
            raise ValueError('The server does not support usage by module / function.')
        labels=dict(group_labels(self.category),other='Other / unclassified')
        rows=[(None, item) for item in groups]
        if self._server_view:
            clients=value.get('clients')
            if not isinstance(clients,list):
                raise ValueError('Server sender accounting is unavailable.')
            index=self.client_filter.currentIndex()
            selected=self.client_filter.currentData()
            if index==1:
                rows=[('All clients',item) for item in groups]
            else:
                rows=[(client['client_id'],item) for client in clients
                      if index==0 or client['client_id']==selected
                      for item in client['groups'] if index!=0 or item.get('requests',0)>0]
                if not rows:
                    rows=[('No recorded client',item) for item in groups]
        keys=[(identity,item['key']) for identity,item in rows]
        if len(set(keys))!=len(keys) or any(key not in labels for _,key in keys):
            raise ValueError('Invalid usage catalog.')
        offset=int(self._server_view)
        self.table.setColumnCount(len(self._fields)+1+offset)
        self.table.setHorizontalHeaderLabels((['Authenticated client'] if offset else [])+
                                            ['Module / function']+[label for label,_ in self._fields])
        self.table.setRowCount(len(rows))
        for row,(identity,item) in enumerate(rows):
            if offset:
                self.table.setItem(row,0,QTableWidgetItem(identity))
            self.table.setItem(row,offset,QTableWidgetItem(labels[item['key']]))
            for column,(_,key) in enumerate(self._fields,1+offset):
                number=item.get(key)
                self.table.setItem(row,column,QTableWidgetItem(f'{number:,}' if type(number) is int and number>=0 else 'Not reported'))
        self.table.horizontalHeaderItem(1+offset).setToolTip('Requests accepted by the server for this module / function.')
        self.table.horizontalHeaderItem(3+offset).setToolTip('Failed, cancelled or interrupted on the server.')
        self.table.horizontalHeaderItem(8+offset).setToolTip('Requests without both reported input and output token counts.')

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self):
        if self._future is not None:
            return
        self.refresh_button.setEnabled(False)
        self.status.setText('Loading retained server usage...')
        self._future = self._pool.submit(self._loader)
        self._timer.start()

    def _poll(self):
        if self._future is None or not self._future.done():
            return
        future,self._future = self._future,None
        self._timer.stop()
        self.refresh_button.setEnabled(True)
        try:
            snapshot=future.result()
            if snapshot.get('version') == 2:
                self._render_user_audit(snapshot)
                return
            if snapshot.get('scope') == 'this_user':
                raise ValueError('Unsupported human usage version.')
            value=snapshot[self.category]
            if not value['available']:
                raise ValueError('Usage history is unavailable for this function.')
            self._server_view=snapshot['scope']=='all_clients_on_this_server'
            self._snapshot=snapshot
            self.client_filter.blockSignals(True)
            selected=self.client_filter.currentData()
            old_index=self.client_filter.currentIndex()
            self.client_filter.clear()
            self.client_filter.setVisible(self._server_view)
            if self._server_view:
                self.client_filter.addItem('All clients - separate rows')
                self.client_filter.addItem('All clients - module totals')
                for client in value.get('clients',[]):
                    self.client_filter.addItem(client['client_id'],client['client_id'])
                chosen=self.client_filter.findData(selected) if selected is not None else min(max(old_index,0),1)
                self.client_filter.setCurrentIndex(max(0,chosen))
            self.client_filter.blockSignals(False)
            self._render(value)
            scope='All clients on this server' if snapshot['scope']=='all_clients_on_this_server' else 'This authenticated sender only'
            self.status.setText(scope + '. Retained history; missing token records are not counted as zero.')
        except Exception:
            self._snapshot=None
            self.client_filter.blockSignals(False)
            self._placeholder('Unavailable')
            self.status.setText('Usage unavailable. Check the shared connection and server version; no provider fallback was used.')
