"""
Stub: zip (or other archive) extractor

TODO: This is a class that takes a zip file and extracts it
  - exposes lists of lmp and txt files, to be consumed elsewhere
"""
class ZipExtractor:

    def __init__(self, file_path):
        self.file_path = file_path
        self.files = self.__extract_files()

    def lmp_files(self):
        return [] # select lmp from self.files

    def txt_files(self):
        return [] # select txt from self.files

    def __extract_files(self):
        return [] # Extract the files from the archive at self.file_path
