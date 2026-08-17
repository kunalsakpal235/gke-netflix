kubectl get deployment,statefulset,hpa -n streaming-staging
kubectl get deployment,statefulset,hpa -n streaming-production

for ns in streaming-staging streaming-production; do
  kubectl delete hpa --all -n $ns
  kubectl scale deployment --all -n $ns --replicas=0
  kubectl scale statefulset --all -n $ns --replicas=0
done

kubectl get pods -n streaming-staging
kubectl get pods -n streaming-production
