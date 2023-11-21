import logo from './logo.svg';
import './App.css';
import { useEffect, useState, useRef } from 'react';
import axios from "axios";
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { Buffer } from 'buffer';

function App() {

  const [user_content, SetUserContent] = useState("")
  const [assist_content, SetAssistContent] = useState("")

  const [element, SetElement] = useState([])

  const [recorderState, SetRecorderState] = useState({
    initRecording: false,
    mediaStream: null,
    mediaRecorder: null,
    audio: null,
  });

  const audioRef = useRef(null)
  const [audioQueue, setAudioQueue] = useState([]);
  const [isPlaying, setIsPlaying] = useState(false);


  const socketUrl = 'ws://localhost:8000/ws';

  const { sendMessage, lastMessage, readyState } = useWebSocket(socketUrl, {
    onOpen: () => {
      console.log('WebSocket connection established.');
    },
    onClose: () => {
      console.log('WebSocket connection closed.');
      // You may implement reconnect logic here
    },
    shouldReconnect: () => true, // Enable automatic reconnection
  });

  // Handle incoming messages from the WebSocket server
  useEffect(() => {
    if (lastMessage !== null) {
      // Handle the incoming message from the WebSocket server
      const dict = JSON.parse(lastMessage.data)
      console.log('Received message:', lastMessage.data);
      appendElement(dict.text)
      setAudioQueue((prev) => [...prev, dict.audio])
    }
  }, [lastMessage]);

  // Send a message to the WebSocket server
  const sendMessageToServer = (message) => {
    sendMessage(message);
  };


  const chunksRef = useRef([])
  const partChunksRef = useRef([])


  // const appendElement = (user_input, res) => {
  //   const newElement = <div>
  //     <p>{"user: " + user_input}</p>
  //     <p>{"assist: " + res}</p>
  //   </div>
  //   SetElement(prevElements => [...prevElements, newElement])
  // }

  const appendElement = (res) => {
    const newElement = res
    SetElement(prevElements => [...prevElements, newElement])
  }

  const appendHorLine = () => {
    SetElement(prev => [...prev, <hr />])
  }

  const getVoiceResponse = (user_content1) => {
    SetAssistContent(() => "")

    axios.post('/chatbot/', user_content1, {
      headers: {
        'Content-Type': 'text/plain',
      },
      transformRequest: [(data) => data],
    })
      .then((res) => {
        changeAssistContent(res.data)
        appendElement(user_content1, res.data['text'])
        playRecording(res.data['audio'])
      })
      .catch((err) => console.log(err));
  }

  const handleSubmit = (e) => {
    e.preventDefault();
    getVoiceResponse(user_content)
  }

  const changeAssistContent = (res) => {
    //console.log(res)
    SetAssistContent(() => res["text"])
  }

  const changeUserContent = (e) => {
    SetUserContent(() => e.target.value)
    //sendMessage(e.target.value)
  }

  async function startRecording() {
    try {
      const constraints = {
        audio: {
          sampleRate: 16000,
          channelCount: 1, // Set the desired number of audio channels
        },
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints)

      SetRecorderState((prevState) => {
        return {
          ...prevState,
          initRecording: true,
          mediaStream: stream,
        }
      })
    } catch (error) {
      console.log(error)
    }

    appendHorLine()
  }

  useEffect(() => {
    if (recorderState.mediaStream) {
      SetRecorderState((prevState) => {
        return {
          ...prevState,
          mediaRecorder: new MediaRecorder(prevState.mediaStream),
        }
      })
    }

  }, [recorderState.mediaStream])

  useEffect(() => {

    if (recorderState.mediaRecorder && recorderState.mediaRecorder.state === "inactive") {
      recorderState.mediaRecorder.start(100)
      sendMessage('Start')

      recorderState.mediaRecorder.addEventListener('dataavailable', handleData)
      recorderState.mediaRecorder.addEventListener("stop", handleStop)

    }
  }, [recorderState.mediaRecorder])

  //for audio queue handling
  useEffect(() => {
    if (!isPlaying && audioQueue.length > 0) {
      playNextAudio()
    }
  })

  const playNextAudio = () => {
    const audioData = audioQueue[0]
    const audioBlob = base64ToBlob(audioData)
    const audioUrl = URL.createObjectURL(new Blob([audioBlob]))

    //play the audio
    audioRef.current.src = audioUrl
    audioRef.current.play();

    //set playing state to true
    setIsPlaying(true)
  }

  const handleAudioEnded = () => {
    // Remove the played audio from the queue
    setAudioQueue((prevQueue) => prevQueue.slice(1));
    // Set playing state to false
    setIsPlaying(false);
  };


  const handleData = async (e) => {

    chunksRef.current.push(e.data)
    // const audioBlob = new Blob([e.data], { type: 'audio/webm;codecs=opus' })
    // const base64 = await blobToBase64(audioBlob)
    // console.log(base64)
    // if (readyState === WebSocket.OPEN) {
    //   sendMessage(e.data)
    // }

  }


  const handleStop = async () => {

    const blob = new Blob(chunksRef.current, { type: 'audio/webm;codecs=opus' })

    // const datetime = (new Date()).toISOString()
    // const name = `file${Date.now()}` + Math.round(Math.random() * 100000)

    // const file = new File([blob], `${name}.webm`)

    if (readyState === WebSocket.OPEN) {
      sendMessage('End')
    }

    chunksRef.current = []
    SetRecorderState(() => {
      return {
        initRecording: false,
        mediaStream: null,
        mediaRecorder: null,
        audio: null,
      }
    })

    //sendData(name, datetime, file)

    // let audioUrl = URL.createObjectURL(blob)
    // let audioElement = new Audio(audioUrl)
    // audioElement.play()
  }

  function blobToBase64(blob) {
    return new Promise((resolve, _) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
  }

  function base64ToBlob(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return new Blob([bytes], { type: 'audio/mpeg' });
  }

  const playRecording = (audio) => {
    //console.log(audio)
    if (audio != null) {
      let audioBlob = base64ToBlob(audio)
      let audioUrl = URL.createObjectURL(new Blob([audioBlob]))
      let audioElement = new Audio(audioUrl)
      audioElement.play()
    }

  }

  const sendData = async (name, datetime, file) => {

    let options = {
      language: "en",
    }

    let formData = new FormData()
    formData.append('file', file, `${name}.webm`)
    formData.append('name', name)
    formData.append('datetime', datetime)
    formData.append('options', JSON.stringify(options))

    console.log("[send data]", (new Date()).toLocaleTimeString())

    axios.post('/whisper/', formData, {
      headers: {
        'Accept': "multipart/form-data",
      },
    })
      .then((res) => {
        console.log(res.data['text'])
        SetUserContent(() => res.data['text'])
        //asking to chatbot once I get text from voice
        getVoiceResponse(res.data['text'])
      })
      .catch((err) => console.log(err));


  }


  function saveRecording() {
    if (recorderState.mediaRecorder.state !== 'inactive') recorderState.mediaRecorder.stop()
  }

  return (
    <div className="App">
      <div id='history'>
        <p>
          {element}
        </p>
      </div>
      <div>
        <audio ref={audioRef} controls onEnded={handleAudioEnded} />
      </div>
      <div>
        <form id='user_chatbot' onSubmit={handleSubmit}>
          <label> User Input:
            <textarea id='userContent' value={user_content} onChange={changeUserContent} />
          </label>
          <label> Assist Output:
            <textarea id='assistContent' value={assist_content} />
          </label>
          <input type='submit' />
        </form>
      </div>
      <div className='start-button-container'>
        {recorderState.initRecording ? (
          <button
            className='start-button'
            title='Save recording'
            onClick={saveRecording}>
            Save
          </button>
        ) : (
          <button className='start-button'
            title='Start recording'
            onClick={startRecording}>
            Start
          </button>
        )
        }
      </div>
    </div>
  );
}

export default App;
