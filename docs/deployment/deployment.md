# Deploying Yesterdays

If you would like to run your own instance of Yesterdays, we encourage you to get in touch.
We'd be glad to support your efforts!

## Kubernetes

We maintain [a helm chart](https://github.com/MapRVA/helm-charts/tree/main/charts/yesterdays) for deploying Yesterdays on Kubernetes clusters.

This chart requires you have the following two operators on your cluster:

- [CloudNativePG](https://cloudnative-pg.io/)
- [RabbitMQ Cluster Kubernetes Operator](https://www.rabbitmq.com/kubernetes/operator/operator-overview)
