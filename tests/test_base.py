from dircloud import read_du_file_maybe

class TestReadDu:

    def test_read_du_file_maybe__key_format(self):
        # Test file generated with: du /boot
        du = read_du_file_maybe('tests/fixtures/du.boot')
        assert du.has_key('boot/') == True
        assert du.has_key('/boot/') == False

    def test_read_du_file_maybe__key_format_final_slash(self):
        # Test file generated with: du /boot/
        du = read_du_file_maybe('tests/fixtures/du.boot_with_final_slash')
        assert du.has_key('boot/') == True
        assert du.has_key('/boot/') == False
