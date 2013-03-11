import sys
import time
import subprocess


def run_dev_server():
    cmd = '%s devserver.py' % (sys.executable,)

    return subprocess.Popen(
        [cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    )


def run_protocol_tests(protocol_test_dir, version):
    cmd = '%s %s/sockjs-protocol-%s.py -v' % (
        sys.executable,
        protocol_test_dir,
        version
    )

    return subprocess.Popen(
        [cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    )


if __name__ == '__main__':
    server_process = run_dev_server()

    time.sleep(1.0)

    test_process = run_protocol_tests(*sys.argv[1:])

    return_code = test_process.wait()
    server_process.kill()

    if return_code:
        print test_process.stdout.read()
        print test_process.stderr.read()

        raise SystemExit(return_code)
