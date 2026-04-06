pipeline {
    agent any

    environment {
        AWS_REGION = 'ap-southeast-2'
        ECR_REGISTRY = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
        ECR_REPO = 'twc-recommendations'
        IMAGE_TAG = "${env.BUILD_NUMBER}-${env.GIT_COMMIT?.take(7) ?: 'latest'}"
        K8S_NAMESPACE = 'recommendations'
    }

    parameters {
        choice(
            name: 'ENVIRONMENT',
            choices: ['staging', 'production'],
            description: 'Deployment environment'
        )
        booleanParam(
            name: 'SKIP_TESTS',
            defaultValue: false,
            description: 'Skip running tests'
        )
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_COMMIT_SHORT = sh(
                        script: 'git rev-parse --short HEAD',
                        returnStdout: true
                    ).trim()
                }
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    python3 -m venv venv
                    . venv/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt
                    pip install pytest pytest-asyncio pytest-cov
                '''
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    . venv/bin/activate
                    pip install ruff
                    ruff check src/ --output-format=github || true
                '''
            }
        }

        stage('Test') {
            when {
                expression { return !params.SKIP_TESTS }
            }
            steps {
                sh '''
                    . venv/bin/activate
                    pytest tests/ \
                        --junitxml=test-results.xml \
                        --cov=src \
                        --cov-report=xml:coverage.xml \
                        --cov-report=html:coverage-html \
                        -v
                '''
            }
            post {
                always {
                    junit 'test-results.xml'
                    publishHTML(target: [
                        allowMissing: true,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: 'coverage-html',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report'
                    ])
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    docker.build("${ECR_REPO}:${IMAGE_TAG}")
                }
            }
        }

        stage('Push to ECR') {
            steps {
                script {
                    sh """
                        aws ecr get-login-password --region ${AWS_REGION} | \
                        docker login --username AWS --password-stdin ${ECR_REGISTRY}
                    """

                    sh """
                        docker tag ${ECR_REPO}:${IMAGE_TAG} ${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}
                        docker tag ${ECR_REPO}:${IMAGE_TAG} ${ECR_REGISTRY}/${ECR_REPO}:latest
                        docker push ${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}
                        docker push ${ECR_REGISTRY}/${ECR_REPO}:latest
                    """
                }
            }
        }

        stage('Deploy to Staging') {
            when {
                expression { return params.ENVIRONMENT == 'staging' }
            }
            steps {
                script {
                    deployToKubernetes('staging')
                }
            }
        }

        stage('Deploy to Production') {
            when {
                expression { return params.ENVIRONMENT == 'production' }
            }
            steps {
                input message: 'Deploy to production?', ok: 'Deploy'
                script {
                    deployToKubernetes('production')
                }
            }
        }

        stage('Verify Deployment') {
            steps {
                sh """
                    kubectl -n ${K8S_NAMESPACE} rollout status deployment/twc-recommendations --timeout=300s
                """
                script {
                    def healthCheck = sh(
                        script: """
                            kubectl -n ${K8S_NAMESPACE} exec deploy/twc-recommendations -- \
                            curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health
                        """,
                        returnStdout: true
                    ).trim()

                    if (healthCheck != '200') {
                        error "Health check failed with status: ${healthCheck}"
                    }
                }
            }
        }
    }

    post {
        success {
            slackSend(
                color: 'good',
                message: "✅ TWC Recommendations deployed successfully\nEnvironment: ${params.ENVIRONMENT}\nImage: ${IMAGE_TAG}"
            )
        }
        failure {
            slackSend(
                color: 'danger',
                message: "❌ TWC Recommendations deployment failed\nEnvironment: ${params.ENVIRONMENT}\nBuild: ${env.BUILD_URL}"
            )
        }
        always {
            cleanWs()
            sh 'docker system prune -f || true'
        }
    }
}

def deployToKubernetes(String environment) {
    def kubeContext = environment == 'production' ? 'eks-prod' : 'eks-staging'

    sh """
        kubectl config use-context ${kubeContext}

        # Apply ConfigMap and Secrets
        kubectl apply -f k8s/configmap.yaml -n ${K8S_NAMESPACE}
        kubectl apply -f k8s/external-secret.yaml -n ${K8S_NAMESPACE} || true

        # Update image in deployment
        kubectl set image deployment/twc-recommendations \
            twc-recommendations=${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG} \
            -n ${K8S_NAMESPACE}

        # Or apply full manifests
        # kubectl apply -f k8s/deployment.yaml -n ${K8S_NAMESPACE}
        # kubectl apply -f k8s/service.yaml -n ${K8S_NAMESPACE}
        # kubectl apply -f k8s/ingress.yaml -n ${K8S_NAMESPACE}
    """
}
