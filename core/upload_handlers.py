from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler


class MaxFileSizeUploadHandler(FileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_size = 0

    def receive_data_chunk(self, raw_data, start):
        self.file_size += len(raw_data)
        if self.file_size > settings.MAX_FILE_UPLOAD_SIZE:
            raise RequestDataTooBig('Uploaded file exceeds the configured size limit.')
        return raw_data

    def file_complete(self, file_size):
        return None
