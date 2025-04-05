from datetime import datetime, timedelta
import uuid  # Import UUID for unique batch IDs
from airflow import DAG
from airflow.providers.google.cloud.operators.dataproc import DataprocCreateBatchOperator
from airflow.providers.google.cloud.sensors.gcs import GCSObjectExistenceSensor
from airflow.models import Variable

# DAG default arguments
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'start_date': datetime(2024, 12, 14),
}


'''In the context of DAGs (Directed Acyclic Graphs) in Apache Airflow, "default args" refers to the default parameters 
that are applied to all tasks within a DAG unless overridden by individual task arguments.

Why Use default_args?
By setting default arguments, you can avoid repeating common configurations (like retries, execution timeouts, etc.) for every task in a DAG. 
These arguments are applied globally to all tasks within the DAG unless a specific task overrides them.'''

# Define the DAG
with DAG(
    dag_id="flight_booking_dataproc_bq_dag",
    default_args=default_args,
    schedule_interval=None,  # Trigger manually or on-demand
    catchup=False,
) as dag:

    # Fetch environment variables
    env = Variable.get("env", default_var="dev")
    gcs_bucket = Variable.get("gcs_bucket", default_var="airflow-projetc-flight")
    bq_project = Variable.get("bq_project", default_var="atomic-voice-454513-h1")
    bq_dataset = Variable.get("bq_dataset", default_var=f"flight_data_{env}")
    tables = Variable.get("tables", deserialize_json=True)

    # Extract table names from the 'tables' variable
    transformed_table = tables["transformed_table"]
    route_insights_table = tables["route_insights_table"]
    origin_insights_table = tables["origin_insights_table"]

    # Generate a unique batch ID using UUID
    batch_id = f"flight-booking-batch-{env}-{str(uuid.uuid4())[:8]}"  # Shortened UUID for brevity

    # # Task 1: File Sensor for GCS
    '''
 In Apache Airflow, a sensor is a special type of operator that waits for a certain condition to be met before continuing. 
 It's used in DAGs (Directed Acyclic Graphs) when you want your pipeline to pause until something external is ready.

Typical use cases:

Waiting for a file to land in a storage bucket

Waiting for a partition/table to appear

Waiting for a specific time or event

Sensors "poke" the condition at intervals (you can configure how often), and once the condition is True, the DAG proceeds.
    '''
    
    # This is a Google Cloud Storage sensor. It waits until a specific object (like a file) exists in a GCS bucket.
    
    file_sensor = GCSObjectExistenceSensor(
        task_id="check_file_arrival",
        bucket=gcs_bucket,
        object=f"airflow-project/source-{env}/flight_booking.csv",  # Full file path in GCS
        google_cloud_conn_id="google_cloud_default",  # GCP connection
        # This was created in Composer in Gcloud so "google_cloud_default" in available in connection in Airflow UI
        timeout=300,  # Timeout in seconds
        poke_interval=30,  # seconds between pokes (Checks)
        mode="poke",  # Blocking mode
        #In Airflow, the mode parameter in a sensor controls how it behaves while waiting.
        #POKE is simple but not efficient for long waits because it holds up resources.
        #mode="reschedule" # More efficient: releases the worker between pokes
    )

    # Task 2: Submit PySpark job to Dataproc Serverless
    batch_details = {
        "pyspark_batch": {
            "main_python_file_uri": f"gs://airflow-projetc-flight/airflow-project/spark-job/spark_job.py",  # Main Python file
            "python_file_uris": [],  # Python WHL files
            "jar_file_uris": [],  # JAR files
            "args": [
                f"--env={env}",
                f"--bq_project={bq_project}",
                f"--bq_dataset={bq_dataset}",
                f"--transformed_table={transformed_table}",
                f"--route_insights_table={route_insights_table}",
                f"--origin_insights_table={origin_insights_table}",
            ]
        },
        "runtime_config": {
            "version": "2.2",  # Specify Dataproc version (if needed)
        },
        "environment_config": {
            "execution_config": {
                "service_account": " 607215282236-compute@developer.gserviceaccount.com",
                "network_uri": "projects/atomic-voice-454513-h1/global/networks/default",
                "subnetwork_uri": "projects/atomic-voice-454513-h1/regions/us-central1/subnetworks/default",
            }
        },
    }

    pyspark_task = DataprocCreateBatchOperator(
        task_id="run_spark_job_on_dataproc_serverless",
        batch=batch_details,
        batch_id=batch_id,
        project_id="psyched-service-442305-q1",
        region="us-central1",
        gcp_conn_id="google_cloud_default",
    )

    # Task Dependencies
    file_sensor >> pyspark_task
