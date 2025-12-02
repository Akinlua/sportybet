process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
import axios from 'axios';
import {HttpsProxyAgent} from 'https-proxy-agent';

const url = 'https://geo.brdtest.com/welcome.txt?product=dc&method=native';
const proxy = 'http://brd-customer-hl_3fa1037b-zone-datacenter_proxy1-country-ng:be0682squyj3@brd.superproxy.io:33335';

(async()=>{
  try {
    const response = await axios.get(url, {
      httpsAgent: new HttpsProxyAgent(proxy)
    });
    console.log(JSON.stringify(response.data, null, 2));
  } catch(error){
    console.error('Error:', error.message);
  }
})();


,
        {
            "username": "7036037447",
            "password": "@IfeeGod2021",
            "active": true,
            "max_concurrent_bets": 20,
            "min_balance": 100,
            "proxy": "http://ng.decodo.com:42011"
        },
        {
            "username": "8149394431",
            "password": "Malima2025",
            "active": true,
            "max_concurrent_bets": 20,
            "min_balance": 100,
            "proxy": "http://ng.decodo.com:42024"
        },
        {
            "username": "7025027406",
            "password": "@Royalbird1",
            "active": true,
            "max_concurrent_bets": 20,
            "min_balance": 100,
            "proxy": "http://ng.decodo.com:42032"
        }

          {
            "username": "9044976808",
            "password": "Amarachi2",
            "active": true,
            "max_concurrent_bets": 20,
            "min_balance": 100,
            "proxy": "http://ng.decodo.com:42001"
        },


