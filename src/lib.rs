use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde_json::json;
use server::AppServer;
use crate::connect::message::MessageManager;
use crate::connect::rpc::RPC;

pub mod base;
pub mod connect;
pub mod macros;
pub mod python;
pub mod server;
pub mod utils;

#[pyfunction]
fn on_output_data(py: Python, data: Py<PyBytes>) -> PyResult<Bound<PyAny>> {
    let bytes = data.as_bytes(py).to_vec();
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let _ = MessageManager::instance()
            .send_stream("play", bytes, None)
            .await;
        Ok(())
    })
}

#[pyfunction]
fn start_server(py: Python) -> PyResult<Bound<PyAny>> {
    pyo3_async_runtimes::tokio::future_into_py(py, async {
        AppServer::run().await;
        Ok(())
    })
}

#[pyfunction]
fn run_shell(py: Python, script: String, timeout_millis: f64) -> PyResult<Bound<PyAny>> {
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let res = RPC::instance()
            .call_remote(
                "run_shell",
                Some(json!(script)),
                Some(timeout_millis as u64),
            )
            .await;
        let result = match res {
            Err(e) => format!("run_shell error: {}", e),
            Ok(res) => serde_json::to_string(&res.data.unwrap()).unwrap(),
        };
        Ok(result)
    })
}

#[pymodule]
fn open_xiaoai_server(_py: Python, m: Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(start_server, &m)?)?;
    m.add_function(wrap_pyfunction!(on_output_data, &m)?)?;
    m.add_function(wrap_pyfunction!(run_shell, &m)?)?;
    crate::python::init_module(&m)?;
    Ok(())
}
