properties(
    [
    buildDiscarder
        (logRotator (
            artifactDaysToKeepStr: '',
            artifactNumToKeepStr: '',
            daysToKeepStr: '14',
            numToKeepStr: '10'
        ) ),
    disableConcurrentBuilds()
    ]
)
pipeline {
    agent {
        docker {
            image 'lsstts/salobj:develop'
            args '--entrypoint "" -u saluser'
        }
    }

    environment {
        work_branches = "${GIT_BRANCH} ${CHANGE_BRANCH} develop"
    }

    stages {
        stage("Checkout ts_utils") {
            steps {
                sh """
                    cd /home/saluser/repos/ts_utils
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Checkout ts_ddsconfig") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repos/ts_ddsconfig
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Checkout ts_sal") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repos/ts_sal
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Checkout ts_xml") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repos/ts_xml
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Checkout ts_idl") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repos/ts_idl
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Build IDL files") {
            steps {
                sh """
                    source ~/.setup.sh
                    make_idl_files.py ESS Test
                """
            }
        }
        stage("Checkout ts_salobj") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repos/ts_salobj
                    /home/saluser/.checkout_repo.sh \${work_branches}
                    git pull
                """
            }
        }
        stage("Run tests") {
            steps {
                sh """
                    source ~/.setup.sh
                    cd /home/saluser/repo/
                    eups declare -r . -t saluser
                    setup ts_watcher -t saluser
                    pytest --junitxml=tests/.tests/junit.xml
                """
            }
        }
    }
    post {
        always {
            // The path of xml needed by JUnit is relative to
            // the workspace.
            junit 'tests/.tests/junit.xml'

            // Publish the HTML report
            publishHTML (target: [
                allowMissing: false,
                alwaysLinkToLastBuild: false,
                keepAll: true,
                reportDir: 'tests/.tests/',
                reportFiles: 'index.html',
                reportName: "Coverage Report"
              ])

            sh """
                source ~/.setup.sh
                cd /home/saluser/repo/
                pip install ltd-conveyor
                setup ts_watcher -t saluser
                package-docs build
                ltd upload --product ts-watcher --git-ref \${GIT_BRANCH} --dir doc/_build/html
            """
        }
    }
}
