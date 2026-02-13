use crate::python::PythonManager;
use crate::base::{AppError, VERSION};
use crate::connect::data::{Event, Request, Response, Stream};
use crate::connect::handler::MessageHandler;
use crate::connect::message::{MessageManager, WsStream};
use crate::connect::rpc::RPC;
use pyo3::types::PyBytes;
use pyo3::types::PyString;
use pyo3::Python;
use serde_json::json;
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::accept_async;

pub struct AppServer;

impl AppServer {
    pub async fn connect(stream: TcpStream) -> Result<WsStream, AppError> {
        let ws_stream = accept_async(stream).await?;
        Ok(WsStream::Server(ws_stream))
    }

    pub async fn run() {
        let addr = "0.0.0.0:4399";
        let listener = TcpListener::bind(addr)
            .await
            .unwrap_or_else(|_| panic!("❌ 绑定地址失败: {}", addr));
        crate::pylog!("✅ 已启动: {:?}", addr);
        while let Ok((stream, addr)) = listener.accept().await {
            // 同一时刻只处理一个连接
            AppServer::handle_connection(stream, addr).await;
        }
    }

    async fn handle_connection(stream: TcpStream, addr: std::net::SocketAddr) {
        let Ok(ws_stream) = AppServer::connect(stream).await else {
            crate::pylog!("❌ 连接异常: {}", addr);
            return;
        };
        crate::pylog!("✅ 已连接: {:?}", addr);
        AppServer::init(ws_stream).await;
        if let Err(e) = MessageManager::instance().process_messages().await {
            crate::pylog!("❌ 消息处理异常: {}", e);
        }
        AppServer::dispose().await;
        crate::pylog!("❌ 已断开连接");
    }

    async fn init(ws_stream: WsStream) {
        MessageManager::instance().init(ws_stream).await;
        MessageHandler::<Event>::instance()
            .set_handler(on_event)
            .await;
        MessageHandler::<Stream>::instance()
            .set_handler(on_stream)
            .await;

        let rpc = RPC::instance();
        rpc.add_command("get_version", get_version).await;
    }

    async fn dispose() {
        MessageManager::instance().dispose().await;
    }
}

async fn get_version(_: Request) -> Result<Response, AppError> {
    let data = json!(VERSION.to_string());
    Ok(Response::from_data(data))
}

async fn on_stream(stream: Stream) -> Result<(), AppError> {
    let Stream { tag, bytes, .. } = stream;
    if tag == "record" {
        let data = Python::with_gil(|py| PyBytes::new(py, &bytes).into());
        PythonManager::instance().call_fn("on_input_data", Some(data))?;
    }
    Ok(())
}

async fn on_event(event: Event) -> Result<(), AppError> {
    let event_json = serde_json::to_string(&event)?;
    let data = Python::with_gil(|py| PyString::new(py, &event_json).into());
    PythonManager::instance().call_fn("on_event", Some(data))?;
    Ok(())
}
