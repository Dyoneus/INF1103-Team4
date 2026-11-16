from abc import ABC, abstractmethod


class StorageInterface(ABC):

    @abstractmethod
    def save_report(self, report):
        pass

    @abstractmethod
    def read_report(self, report_path):
        pass

    @abstractmethod
    def write_report(self, report_path, report):
        pass

    @abstractmethod
    def delete_report(self, reference_id):
        pass
