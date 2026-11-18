/*
 * Copyright (c) 2022-2024 Qualcomm Innovation Center, Inc. All rights reserved.
 *
 * Permission to use, copy, modify, and/or distribute this software for
 * any purpose with or without fee is hereby granted, provided that the
 * above copyright notice and this permission notice appear in all
 * copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
 * WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE
 * AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL
 * DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR
 * PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
 * TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
 * PERFORMANCE OF THIS SOFTWARE.
 */
/*
 * Exact unfixed production functions retained only for the negative control.
 * Origin: modules/qcacld-3.0/components/dp/core/src/wlan_dp_txrx.c
 * Frozen original full-source SHA-256:
 * c6797d865f15f8dc3cf1f0366358de2fd6311cdb916210ffbc18f4d3446a326b
 * These functions predate monitor MAC-header/protocol initialization.
 */
static enum dp_nbuf_push_type dp_mon_rx_push_type(struct net_device *dev)
{
#ifdef FEATURE_WLAN_WONDER
	/* Final publication holds radio admission. Wonder's mac80211 RX handler
	 * can transmit a reply, so enqueue it instead of calling it recursively
	 * through netif_receive_skb while the admission lock is still held.
	 */
	if (hdd_wonder_netdev_is_owned(dev))
		return DP_NBUF_PUSH_SIMPLE;
#endif
	return qdf_in_atomic() ? DP_NBUF_PUSH_NAPI : DP_NBUF_PUSH_BH_DISABLE;
}

QDF_STATUS dp_mon_rx_packet_cbk(void *context, qdf_nbuf_t rxbuf)
{
	struct wlan_dp_intf *dp_intf;
	struct wlan_dp_link *dp_link;
	QDF_STATUS status;
	qdf_nbuf_t nbuf;
	qdf_nbuf_t nbuf_next;
	unsigned int cpu_index;
	struct dp_tx_rx_stats *stats;
	enum dp_nbuf_push_type type;

	/* Sanity check on inputs */
	if ((!context) || (!rxbuf)) {
		dp_err_rl("Null params being passed");
		return QDF_STATUS_E_FAILURE;
	}

	dp_link = (struct wlan_dp_link *)context;
	dp_intf = dp_link->dp_intf;
	if (!dp_intf) {
		dp_err_rl("dp_intf is NULL for dp_link %pK", dp_link);
		return QDF_STATUS_E_FAILURE;
	}

	cpu_index = qdf_get_cpu();
	stats = &dp_intf->dp_stats.tx_rx_stats;

	/* walk the chain until all are processed */
	nbuf =  rxbuf;
	while (nbuf) {
		nbuf_next = qdf_nbuf_next(nbuf);
#ifdef FEATURE_WLAN_WONDER
		if (dp_intf->dev && !hdd_wonder_netdev_transport_ready(dp_intf->dev)) {
			qdf_nbuf_set_next(nbuf, NULL);
			qdf_nbuf_free(nbuf);
			++stats->per_cpu[cpu_index].rx_refused;
			nbuf = nbuf_next;
			continue;
		}
#endif
		qdf_nbuf_set_dev(nbuf, dp_intf->dev);

		++stats->per_cpu[cpu_index].rx_packets;
		qdf_net_stats_add_rx_pkts(&dp_intf->stats, 1);
		qdf_net_stats_add_rx_bytes(&dp_intf->stats,
					   qdf_nbuf_len(nbuf));

		/* Remove SKB from internal tracking table before submitting
		 * it to stack
		 */
		qdf_net_buf_debug_release_skb(nbuf);

		/*
		 * If this is not a last packet on the chain
		 * Just put packet into backlog queue, not scheduling RX sirq
		 */
		if (qdf_nbuf_next(nbuf)) {
			status = dp_intf->dp_ctx->dp_ops.dp_nbuf_push_pkt(nbuf,
							DP_NBUF_PUSH_SIMPLE);
		} else {
			/*
			 * This is the last packet on the chain
			 * Scheduling rx sirq
			 */
			type = dp_mon_rx_push_type(dp_intf->dev);
			status = dp_intf->dp_ctx->dp_ops.dp_nbuf_push_pkt(nbuf,
							type);
		}

		if (QDF_IS_STATUS_SUCCESS(status))
			++stats->per_cpu[cpu_index].rx_delivered;
		else
			++stats->per_cpu[cpu_index].rx_refused;

		nbuf = nbuf_next;
	}

	return QDF_STATUS_SUCCESS;
}
